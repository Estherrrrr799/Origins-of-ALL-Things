// engine_turn_structure_check.js
// =============================================================================
// 800回合上限合理性验证 —— 引擎结构实测脚本
//
// 目的：直接复用 simulation_baseline_en.html / simulation_en.html 的核心引擎
// （buildDeck / shuffle / srt / getGrp / findValidSet / extractSets / checkWin /
//  calcScore / ruleAI / evalH / oneSGSAI / randomAI / runAI），逻辑与网页版
// 完全一致、未做任何改动，只在 simulateOneGameInstrumented() 里加了监测代码，
// 用来回答："800回合上限是否合理" 这个问题背后的结构性事实：
//   1. 摸牌堆（48张）在第几回合耗尽？
//   2. 有效（未超时）对局的总回合数分布是多少？
//   3. 超时对局里，最后一次真正调用 AI 做决策发生在第几回合
//      （lastActiveTurn）？之后到第800回合之间，是否存在任何决策？
//   4. 超时对局结束时，四个座位的手牌是否已经全部清零
//      （即"无牌可打"的确定性僵局，而非"差一点点没分出胜负"）？
//
// 输出：output/turn_structure_raw.csv，每局一行，供 Python 脚本
// （analyze_turn_structure.py）做精确统计和绘图。
//
// 用法： node engine_turn_structure_check.js
// =============================================================================

const fs = require("fs");
const path = require("path");

const SPECIES = [
  { id: "plant" }, { id: "star" }, { id: "butterfly" }, { id: "fruit" },
  { id: "human" }, { id: "water" }, { id: "flower" },
];
const SPO = SPECIES.map(s => s.id);

function buildDeck() {
  const d = [];
  for (const s of SPECIES)
    for (const v of [1, 2, 3])
      for (let c = 0; c < 4; c++)
        d.push({ species: s.id, variant: v, id: `${s.id}-${v}-${c}` });
  return d;
}

function shuffle(a) {
  const r = [...a];
  for (let i = r.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [r[i], r[j]] = [r[j], r[i]];
  }
  return r;
}

function srt(h) {
  return [...h].sort((a, b) => {
    const d = SPO.indexOf(a.species) - SPO.indexOf(b.species);
    return d || a.variant - b.variant;
  });
}

function getGrp(h) {
  const g = {};
  for (const c of h) {
    if (!g[c.species]) g[c.species] = [];
    g[c.species].push(c);
  }
  return g;
}

function findValidSet(cards) {
  for (const v of [1, 2, 3]) {
    const same = cards.filter(c => c.variant === v);
    if (same.length >= 3) return { type: "evo", cards: same.slice(0, 3) };
  }
  const v1 = cards.find(c => c.variant === 1), v2 = cards.find(c => c.variant === 2), v3 = cards.find(c => c.variant === 3);
  if (v1 && v2 && v3) return { type: "abs", cards: [v1, v2, v3] };
  return null;
}

function extractSets(hand) {
  const g = getGrp(hand);
  const ext = [];
  let nh = [...hand];
  for (const [sp, cards] of Object.entries(g)) {
    if (cards.length >= 3) {
      const valid = findValidSet(cards);
      if (valid) {
        ext.push({ species: sp, type: valid.type, cards: valid.cards });
        const ids = new Set(valid.cards.map(c => c.id));
        nh = nh.filter(c => !ids.has(c.id));
      }
    }
  }
  return { newHand: srt(nh), extracted: ext };
}

function checkWin(h, sets) {
  return h.length === 0 && sets.length === 3;
}

function calcScore(sets, bonus) {
  let b = 10;
  if (sets.every(s => {
    const vs = s.cards.map(c => c.variant).sort();
    return vs[0] === vs[1] && vs[1] === vs[2];
  })) b = Math.max(b, 15);
  if (bonus?.kaoZiji) b = Math.max(b, 15);
  if (bonus?.tianZhi) b = 30;
  return b;
}

function ruleAI(hand, last, ca) {
  const g = getGrp(hand);
  if (ca && last) {
    const matching = hand.filter(c => c.species === last.species);
    if (matching.length >= 2) {
      let bestPair = null;
      for (let i = 0; i < matching.length; i++)
        for (let j = i + 1; j < matching.length; j++) {
          if (findValidSet([matching[i], matching[j], last])) {
            bestPair = [matching[i], matching[j]];
            break;
          }
          if (bestPair) break;
        }
      if (bestPair) {
        const keepIds = new Set([...bestPair.map(c => c.id), last.id]);
        const discardPool = hand.filter(c => !keepIds.has(c.id));
        if (discardPool.length > 0) {
          const poolGrp = getGrp(discardPool);
          const singletons = Object.entries(poolGrp).filter(([, a]) => a.length === 1);
          const pairs = Object.entries(poolGrp).filter(([, a]) => a.length === 2);
          let d;
          if (singletons.length) d = singletons[0][1][0];
          else if (pairs.length) d = pairs[0][1][0];
          else d = discardPool[0];
          return { action: "absorb", discard: d };
        }
      }
    }
  }
  const sg = Object.entries(g).filter(([, a]) => a.length === 1);
  if (sg.length) return { action: "play", card: sg[0][1][0] };
  const pr = Object.entries(g).filter(([, a]) => a.length === 2);
  if (pr.length) return { action: "play", card: pr[0][1][0] };
  return { action: "play", card: hand[0] };
}

function evalH(h) {
  const g = getGrp(h);
  let s = 0;
  for (const [, cards] of Object.entries(g)) {
    const valid = findValidSet(cards);
    if (valid) { s += 100; continue; }
    if (cards.length >= 2) {
      const vc = {};
      cards.forEach(c => { vc[c.variant] = (vc[c.variant] || 0) + 1; });
      const maxSame = Math.max(...Object.values(vc));
      const uniq = Object.keys(vc).length;
      if (maxSame >= 2) s += 20;
      if (uniq === 2 && cards.length === 2) s += 15;
      if (uniq === 3) s += 25;
    } else s -= 5;
  }
  return s;
}

function oneSGSAI(hand, last, ca) {
  let best = -Infinity, mv = null;
  if (ca && last) {
    const matching = hand.filter(c => c.species === last.species);
    if (matching.length >= 2) {
      for (let i = 0; i < matching.length; i++)
        for (let j = i + 1; j < matching.length; j++) {
          if (findValidSet([matching[i], matching[j], last])) {
            const keepIds = new Set([matching[i].id, matching[j].id, last.id]);
            for (const d of hand) {
              if (keepIds.has(d.id)) continue;
              const nh = [...hand.filter(c => c.id !== d.id), last];
              const s = evalH(nh);
              if (s > best) { best = s; mv = { action: "absorb", discard: d }; }
            }
          }
        }
    }
  }
  for (const card of hand) {
    const s = evalH(hand.filter(c => c.id !== card.id));
    if (s > best) { best = s; mv = { action: "play", card }; }
  }
  return mv || { action: "play", card: hand[0] };
}

function randomAI(hand, last, ca) {
  if (ca && last) {
    const matching = hand.filter(c => c.species === last.species);
    if (matching.length >= 2) {
      const validPairs = [];
      for (let i = 0; i < matching.length; i++)
        for (let j = i + 1; j < matching.length; j++) {
          if (findValidSet([matching[i], matching[j], last]))
            validPairs.push([matching[i], matching[j]]);
        }
      if (validPairs.length) {
        const pair = validPairs[Math.floor(Math.random() * validPairs.length)];
        const keepIds = new Set([...pair.map(c => c.id), last.id]);
        const discardPool = hand.filter(c => !keepIds.has(c.id));
        if (discardPool.length > 0) {
          const d = discardPool[Math.floor(Math.random() * discardPool.length)];
          return { action: "absorb", discard: d };
        }
      }
    }
  }
  const card = hand[Math.floor(Math.random() * hand.length)];
  return { action: "play", card };
}

function runAI(mode, h, l, ca) {
  return mode === "rule" ? ruleAI(h, l, ca) : mode === "oneSGS" ? oneSGSAI(h, l, ca) : randomAI(h, l, ca);
}

const MAX_TURNS = 800;

// ─────────────────────────────────────────────────────────────────────────
// [NEW] 带监测的对局模拟：游戏逻辑与原版 simulateOneGame 逐行一致（未做任何
// 改动），只多记录了：
//   - lastActiveTurn：全场最后一次真正调用 runAI() 做决策发生在第几回合
//   - drawPileExhaustedAtTurn：摸牌堆（48张）耗尽的回合
//   - handsAtEndSum：游戏结束（含超时）时，四个座位手牌剩余张数之和
// ─────────────────────────────────────────────────────────────────────────
function simulateOneGameInstrumented(aiTypes) {
  const deck = shuffle(buildDeck());
  let hands = [srt(deck.slice(0, 9)), srt(deck.slice(9, 18)), srt(deck.slice(18, 27)), srt(deck.slice(27, 36))];
  let drawPile = deck.slice(36);
  let completed = [[], [], [], []];
  let bonuses = [{ kaoZiji: true }, { kaoZiji: true }, { kaoZiji: true }, { kaoZiji: true }];
  let lastCard = null;

  let absorbEvoCount = 0;
  let turnCount = 0;
  let winner = null;
  let winnerScore = 0;

  let lastActiveTurn = 0;
  let totalActiveTurns = 0;
  let drawPileExhaustedAtTurn = null;

  const drawCard = (pi) => {
    if (drawPile.length === 0) return;
    const drawn = drawPile[0];
    drawPile = drawPile.slice(1);
    hands[pi] = srt([...hands[pi], drawn]);
    if (drawPile.length === 0 && drawPileExhaustedAtTurn === null) drawPileExhaustedAtTurn = turnCount;
  };
  const applyExtract = (pi) => {
    const { newHand, extracted } = extractSets(hands[pi]);
    if (extracted.length === 0) return;
    hands[pi] = newHand;
    completed[pi] = [...completed[pi], ...extracted];
    absorbEvoCount += extracted.length;
  };
  const checkWinner = (pi) => {
    if (checkWin(hands[pi], completed[pi])) {
      winner = pi;
      winnerScore = calcScore(completed[pi], bonuses[pi]);
      return true;
    }
    return false;
  };

  let current = 0;

  while (turnCount < MAX_TURNS) {
    turnCount++;
    const mode = aiTypes[current];
    const hand = hands[current];

    if (hand.length === 0) {
      current = (current + 1) % 4;
      continue;
    }

    let acted = false;
    if (lastCard) {
      const matching = hand.filter(c => c.species === lastCard.species);
      if (matching.length >= 2) {
        let hasValid = false;
        outer: for (let i = 0; i < matching.length; i++) for (let j = i + 1; j < matching.length; j++) {
          if (findValidSet([matching[i], matching[j], lastCard])) { hasValid = true; break outer; }
        }
        if (hasValid) {
          const mv = runAI(mode, hand, lastCard, true);
          totalActiveTurns++; lastActiveTurn = turnCount;
          if (mv.action === "absorb") {
            const afterAbs = srt([...hand.filter(c => c.id !== mv.discard.id), lastCard]);
            const playMv = runAI(mode, afterAbs, null, false);
            totalActiveTurns++; lastActiveTurn = turnCount;
            hands[current] = srt(afterAbs.filter(c => c.id !== playMv.card.id));
            bonuses[current] = { ...bonuses[current], kaoZiji: false };
            drawCard(current);
            applyExtract(current);
            if (checkWinner(current)) break;
            lastCard = playMv.card;
            acted = true;
          }
        }
      }
    }

    if (!acted) {
      const mv = runAI(mode, hand, null, false);
      totalActiveTurns++; lastActiveTurn = turnCount;
      hands[current] = srt(hand.filter(c => c.id !== mv.card.id));
      drawCard(current);
      applyExtract(current);
      if (checkWinner(current)) break;
      lastCard = mv.card;
    }

    current = (current + 1) % 4;
  }

  const handsAtEndSum = hands.reduce((a, h) => a + h.length, 0);

  return {
    timedOut: winner === null,
    totalTurns: turnCount,
    lastActiveTurn,
    idleTurns: turnCount - lastActiveTurn,
    drawPileExhaustedAtTurn,
    handsAtEndSum,
  };
}

// ─────────────────────────────────────────────────────────────────────────
// 批量运行，覆盖所有matchup类型
// ─────────────────────────────────────────────────────────────────────────
const MATCHUPS = [
  { key: "rule_vs_1SGS", seats: ["rule", "oneSGS", "rule", "oneSGS"] },
  { key: "rule_vs_rule", seats: ["rule", "rule", "rule", "rule"] },
  { key: "1SGS_vs_1SGS", seats: ["oneSGS", "oneSGS", "oneSGS", "oneSGS"] },
  { key: "rule_vs_random", seats: ["rule", "random", "rule", "random"] },
  { key: "1SGS_vs_random", seats: ["oneSGS", "random", "oneSGS", "random"] },
  { key: "random_vs_random", seats: ["random", "random", "random", "random"] },
];

const N_PER_MATCHUP = 5000;

const outPath = path.join(__dirname, "data", "turn_structure_raw.csv");
const header = "matchup,game_id,timed_out,total_turns,last_active_turn,idle_turns,draw_pile_exhausted_turn,hands_at_end_sum\n";
const lines = [header];

console.log(`每个matchup跑 ${N_PER_MATCHUP} 局，共 ${MATCHUPS.length} 个matchup...`);
for (const m of MATCHUPS) {
  const t0 = Date.now();
  for (let i = 0; i < N_PER_MATCHUP; i++) {
    const r = simulateOneGameInstrumented(m.seats);
    lines.push(`${m.key},${i + 1},${r.timedOut ? 1 : 0},${r.totalTurns},${r.lastActiveTurn},${r.idleTurns},${r.drawPileExhaustedAtTurn ?? ""},${r.handsAtEndSum}\n`);
  }
  console.log(`  [${m.key}] 完成，用时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}

fs.writeFileSync(outPath, lines.join(""), "utf8");
console.log(`\n原始数据已写入: ${outPath}`);
console.log(`总行数: ${lines.length - 1}`);
