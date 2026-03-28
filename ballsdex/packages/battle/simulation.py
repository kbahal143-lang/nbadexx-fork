"""
Basketball match simulation engine for the Battle package.

Flow:
  1. build_sim_teams()   — converts DB Team + positions into PlayerSim / TeamSim
  2. run_match()         — runs the full game with real-time Discord embed updates
"""

import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional

import discord

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlayerSim:
    name: str
    position: str        # PG / SG / SF / PF / C
    offense: int         # computed attack stat
    defense: int         # computed health stat
    rarity: float        # 0.0 – 1.0 → scaled to 0-100 overall

    # Game-time accumulation
    pts: int = 0
    reb: int = 0
    ast: int = 0
    stl: int = 0
    blk: int = 0
    to: int = 0
    fgm: int = 0
    fga: int = 0
    tpm: int = 0         # 3-pointers made
    tpa: int = 0
    ftm: int = 0
    fta: int = 0

    @property
    def overall(self) -> float:
        return self.rarity * 100

    @property
    def fg_pct(self) -> str:
        if self.fga == 0:
            return ".000"
        return f".{int(self.fgm / self.fga * 1000):03d}"

    @property
    def short_name(self) -> str:
        parts = self.name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}. {parts[-1]}"
        return self.name


@dataclass
class TeamSim:
    owner: str
    pg: Optional[PlayerSim] = None
    sg: Optional[PlayerSim] = None
    sf: Optional[PlayerSim] = None
    pf: Optional[PlayerSim] = None
    c:  Optional[PlayerSim] = None
    score: int = 0

    def players(self) -> list[PlayerSim]:
        return [p for p in [self.pg, self.sg, self.sf, self.pf, self.c] if p]

    def pick_ball_handler(self) -> PlayerSim:
        """Pick who initiates this possession (weighted by role)."""
        weights = {"PG": 35, "SG": 25, "SF": 20, "PF": 12, "C": 8}
        pool: list[PlayerSim] = []
        for p in self.players():
            pool.extend([p] * weights.get(p.position, 10))
        return random.choice(pool)

    def pick_defender(self, attacker: PlayerSim) -> PlayerSim:
        """Pick the primary defender (matching position preferred)."""
        same_pos = [p for p in self.players() if p.position == attacker.position]
        if same_pos:
            return random.choice(same_pos)
        return random.choice(self.players())

    def pick_rebounder(self) -> PlayerSim:
        weights = {"PG": 5, "SG": 8, "SF": 15, "PF": 28, "C": 35}
        pool: list[PlayerSim] = []
        for p in self.players():
            pool.extend([p] * weights.get(p.position, 10))
        return random.choice(pool)

    def pick_passer(self, scorer: PlayerSim) -> Optional[PlayerSim]:
        """Pick an assisting player (not the scorer)."""
        others = [p for p in self.players() if p is not scorer]
        if not others:
            return None
        weights = {"PG": 40, "SG": 20, "SF": 15, "PF": 12, "C": 8}
        pool: list[PlayerSim] = []
        for p in others:
            pool.extend([p] * weights.get(p.position, 10))
        return random.choice(pool)

    def team_offense(self) -> float:
        return sum(p.offense for p in self.players()) / max(1, len(self.players()))

    def team_defense(self) -> float:
        return sum(p.defense for p in self.players()) / max(1, len(self.players()))


# ─────────────────────────────────────────────────────────────────────────────
# Position-based skill modifiers
# ─────────────────────────────────────────────────────────────────────────────

POS_SHOT_DIST = {
    "PG": {"paint": 0.25, "mid":   0.30, "three": 0.45},
    "SG": {"paint": 0.22, "mid":   0.28, "three": 0.50},
    "SF": {"paint": 0.35, "mid":   0.32, "three": 0.33},
    "PF": {"paint": 0.55, "mid":   0.33, "three": 0.12},
    "C":  {"paint": 0.72, "mid":   0.22, "three": 0.06},
}

POS_BASE_MAKE = {
    "paint": 0.60,
    "mid":   0.44,
    "three": 0.37,
}

MOVE_TEMPLATES = {
    "paint": [
        "{a} drives hard to the basket",
        "{a} catches the lob and SLAMS",
        "{a} powers through contact in the paint",
        "{a} spins and lays it off the glass",
        "{a} throws down the PUT-BACK SLAM",
        "{a} catches in the post and scores",
        "{a} rises up for the two-handed DUNK",
        "{a} drops in the hook shot",
    ],
    "mid": [
        "{a} rises for the mid-range JUMPER",
        "{a} pulls up off the dribble",
        "{a} hits the floater over the defense",
        "{a} catches and fires from the elbow",
        "{a} drains the step-back mid-ranger",
        "{a} hits the turnaround jumper",
        "{a} isolates and nails the pull-up",
    ],
    "three": [
        "{a} fires from DOWNTOWN",
        "{a} steps back and lets it fly",
        "{a} catches and BOMBS the three",
        "{a} pulls up from deep — SPLASH",
        "{a} drains the corner THREE",
        "{a} launches from 30 feet",
        "{a} hits the step-back triple",
    ],
}

MISS_TEMPLATES = {
    "paint": [
        "{a} misses the layup — off the backboard",
        "{a} is rejected at the rim",
        "{a} throws the runner — rattles out",
    ],
    "mid": [
        "{a} fires the mid-range — no good",
        "{a} misses the pull-up jumper",
        "{a} loses the ball on the fadeaway",
    ],
    "three": [
        "{a} misses the three — long rebound",
        "{a} launches from deep — bricks it",
        "{a} fires off-balance — no good",
    ],
}

STEAL_TEMPLATES = [
    "{d} picks the pocket of {a} — STEAL 🫰",
    "{d} deflects the pass — STEAL!",
    "{d} anticipates the dribble — takes it away",
    "{d} jumps the passing lane for the STEAL",
]

BLOCK_TEMPLATES = [
    "{d} SWATS it into the third row — BLOCK 🧱",
    "{d} rises and REJECTS {a} at the rim",
    "{d} sends it flying — massive BLOCK!",
    "{d} denies {a} completely at the basket",
]

TO_TEMPLATES = [
    "{a} loses the handle — TURNOVER",
    "{a} dribbles off their own foot",
    "{a} throws it away out of bounds",
    "{a} commits a five-second violation",
    "{a} is called for a travel",
]

FAST_BREAK_TEMPLATES = [
    "🚀 Fast break! {a} finishes in transition",
    "⚡ {a} takes it the length of the court",
    "🏃 {a} ahead of the defense for the AND-1",
]

FOUL_TEMPLATES = [
    "{d} hacks {a} — sends them to the line",
    "{d} commits a reach-in foul on {a}",
    "{a} draws the foul on {d}",
]

# ─────────────────────────────────────────────────────────────────────────────
# Core possession generator
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_possession(
    attacking: TeamSim,
    defending: TeamSim,
    run_length: list[int],
) -> tuple[str, int, str]:
    """
    Simulate one possession.
    Returns (play_text, points_scored, emoji_prefix).
    """
    attacker = attacking.pick_ball_handler()
    defender = defending.pick_defender(attacker)

    roll = random.random()

    # Steal / TO  (~15% of possessions)
    stl_chance = 0.08 * (1 + (defender.defense - attacker.offense) / 600)
    stl_chance = max(0.03, min(0.14, stl_chance))
    to_chance = 0.07

    if roll < stl_chance:
        defender.stl += 1
        attacker.to += 1
        run_length[0] = 0
        template = random.choice(STEAL_TEMPLATES)
        text = template.format(a=attacker.short_name, d=defender.short_name)
        return f"🛡️ {text}", 0, "steal"

    if roll < stl_chance + to_chance:
        attacker.to += 1
        run_length[0] = 0
        template = random.choice(TO_TEMPLATES)
        text = template.format(a=attacker.short_name)
        return f"💨 {text}", 0, "to"

    # Foul (~8%)
    foul_roll = random.random()
    if foul_roll < 0.08:
        atk_off_bonus = attacker.offense / 300
        ft_made = 0
        for _ in range(2):
            if random.random() < 0.75 + atk_off_bonus * 0.1:
                ft_made += 1
        attacker.fta += 2
        attacker.ftm += ft_made
        attacker.pts += ft_made
        attacking.score += ft_made
        template = random.choice(FOUL_TEMPLATES)
        text = template.format(a=attacker.short_name, d=defender.short_name)
        run_length[0] += ft_made
        return f"🆓 {text} — {ft_made}/2 FT", ft_made, "foul"

    # Shot attempt
    dist_weights = POS_SHOT_DIST[attacker.position]
    r = random.random()
    if r < dist_weights["paint"]:
        shot_type = "paint"
    elif r < dist_weights["paint"] + dist_weights["mid"]:
        shot_type = "mid"
    else:
        shot_type = "three"

    pts_value = 3 if shot_type == "three" else 2

    # Determine if made
    off_rating = attacker.offense / 300          # normalise to ~0.33 at avg
    def_rating = defender.defense / 300
    base_make = POS_BASE_MAKE[shot_type]
    make_prob = base_make + (off_rating - def_rating) * 0.15
    make_prob = max(0.20, min(0.75, make_prob))

    attacker.fga += 1
    if shot_type == "three":
        attacker.tpa += 1

    if random.random() < make_prob:
        # Made shot
        attacker.fgm += 1
        attacker.pts += pts_value
        attacking.score += pts_value
        if shot_type == "three":
            attacker.tpm += 1
        run_length[0] += pts_value

        # Assist chance
        assist_chance = {"PG": 0.45, "SG": 0.35, "SF": 0.28, "PF": 0.20, "C": 0.12}
        passer = None
        if random.random() < assist_chance.get(attacker.position, 0.25):
            passer = attacking.pick_passer(attacker)
            if passer:
                passer.ast += 1

        template = random.choice(MOVE_TEMPLATES[shot_type])
        text = template.format(a=attacker.short_name)

        if passer:
            text = f"{passer.short_name} finds {attacker.short_name} — {text.split(' — ')[-1] if ' — ' in text else text}"

        suffix = f" (+{pts_value})"
        if shot_type == "three":
            emoji = "🎯"
        elif shot_type == "paint" and ("SLAM" in text or "DUNK" in text):
            emoji = "💪"
        else:
            emoji = "🏀"

        # Block check (even on made shots sometimes the initial attempt is blocked)
        blk_chance = 0.04 * (defender.defense / 300)
        if random.random() < blk_chance and shot_type == "paint":
            defender.blk += 1
            attacker.fgm -= 1
            attacker.pts -= pts_value
            attacking.score -= pts_value
            run_length[0] -= pts_value
            blk_tmpl = random.choice(BLOCK_TEMPLATES)
            blk_text = blk_tmpl.format(a=attacker.short_name, d=defender.short_name)
            reb = defending.pick_rebounder()
            reb.reb += 1
            return f"🧱 {blk_text} — {reb.short_name} with the reb", 0, "block"

        run_str = ""
        if run_length[0] >= 6:
            run_str = f" 🔥 {attacking.owner} ON A RUN!"

        return f"{emoji} {text}{suffix}{run_str}", pts_value, "make"

    else:
        # Missed shot
        run_length[0] = 0
        template = random.choice(MISS_TEMPLATES[shot_type])
        text = template.format(a=attacker.short_name)

        # Rebound
        off_reb_chance = 0.27
        if random.random() < off_reb_chance:
            reb = attacking.pick_rebounder()
            reb.reb += 1
            return f"💨 {text} — {reb.short_name} offensive BOARD", 0, "miss"
        else:
            reb = defending.pick_rebounder()
            reb.reb += 1
            return f"💨 {text} — {reb.short_name} cleans up", 0, "miss"


# ─────────────────────────────────────────────────────────────────────────────
# Build simulation teams from DB objects
# ─────────────────────────────────────────────────────────────────────────────

def build_player_sim(inst, position: str) -> PlayerSim:
    return PlayerSim(
        name=inst.ball.country,
        position=position,
        offense=inst.attack,
        defense=inst.health,
        rarity=inst.ball.rarity,
    )


def build_sim_teams(owner_a: str, slots_a: dict, owner_b: str, slots_b: dict) -> tuple[TeamSim, TeamSim]:
    def build(owner, slots):
        t = TeamSim(owner=owner)
        for pos in ("PG", "SG", "SF", "PF", "C"):
            inst = slots.get(pos)
            if inst:
                setattr(t, pos.lower(), build_player_sim(inst, pos))
        return t
    return build(owner_a, slots_a), build(owner_b, slots_b)


# ─────────────────────────────────────────────────────────────────────────────
# Live embed builders
# ─────────────────────────────────────────────────────────────────────────────

def _score_bar(team_a: TeamSim, team_b: TeamSim) -> str:
    return (
        f"🟠 **{team_a.owner}** · **{team_a.score}**\n"
        f"🔵 **{team_b.owner}** · **{team_b.score}**"
    )


def _build_live_embed(
    team_a: TeamSim,
    team_b: TeamSim,
    quarter: int,
    clock: str,
    plays: list[str],
    overtime: bool = False,
) -> discord.Embed:
    if overtime:
        title = "🏀 OVERTIME"
        color = 0xFF6600
    else:
        title = f"🏀 LIVE  |  Q{quarter}  ·  {clock}"
        color = 0xE8501A

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="─── Score ───", value=_score_bar(team_a, team_b), inline=False)

    if plays:
        log_text = "\n".join(plays[-10:])
        embed.add_field(name="📋 Play by Play", value=log_text, inline=False)

    return embed


def _fmt_player_stats(p: PlayerSim) -> str:
    return (
        f"**{p.short_name}** `[{p.position}]`  "
        f"{p.pts} pts · {p.reb} reb · {p.ast} ast · "
        f"{p.stl} stl · {p.blk} blk · "
        f"{p.fgm}/{p.fga} FG · {p.tpm}/{p.tpa} 3P"
    )


def _build_final_embed(
    team_a: TeamSim,
    team_b: TeamSim,
    winner: TeamSim,
    loser: TeamSim,
    stake_winner_text: str,
    stake_loser_text: str,
    overtime: bool,
) -> discord.Embed:
    ot_str = "  (OT)" if overtime else ""
    embed = discord.Embed(
        title=f"🏆  FINAL SCORE{ot_str}",
        description=(
            f"**{team_a.owner}  {team_a.score}  —  {team_b.score}  {team_b.owner}**\n\n"
            f"🏆  **{winner.owner} WINS!**"
        ),
        color=0xFFD700,
    )

    # Team A stats
    a_stats = "\n".join(_fmt_player_stats(p) for p in team_a.players())
    embed.add_field(name=f"🟠  {team_a.owner}'s Stats", value=a_stats or "—", inline=False)

    # Team B stats
    b_stats = "\n".join(_fmt_player_stats(p) for p in team_b.players())
    embed.add_field(name=f"🔵  {team_b.owner}'s Stats", value=b_stats or "—", inline=False)

    # Stakes
    if stake_winner_text or stake_loser_text:
        stakes_text = ""
        if stake_winner_text:
            stakes_text += f"**{winner.owner} staked:** {stake_winner_text}\n"
        if stake_loser_text:
            stakes_text += f"**{loser.owner} staked:** {stake_loser_text}"
        embed.add_field(
            name=f"💰  {winner.owner} takes all stakes!",
            value=stakes_text.strip() or "No stakes.",
            inline=False,
        )

    embed.set_footer(text="Thanks for playing NBADex Battle!")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Main simulation runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_match(
    team_a: TeamSim,
    team_b: TeamSim,
    message: discord.Message,
    stakes_a_text: str = "",
    stakes_b_text: str = "",
) -> TeamSim:
    """
    Run a full simulated basketball game, editing *message* in real-time.
    Returns the winning TeamSim.
    """
    plays: list[str] = []
    overtime = False
    game_minute_counter = 0

    run_a: list[int] = [0]
    run_b: list[int] = [0]

    async def push_update(quarter: int, clock: str, ot: bool = False):
        try:
            embed = _build_live_embed(team_a, team_b, quarter, clock, plays, overtime=ot)
            await message.edit(embed=embed)
        except Exception:
            pass
        await asyncio.sleep(3)

    for q in range(1, 5):
        plays.append(f"\n**━━  QUARTER {q}  ━━**\n")
        await push_update(q, "12:00")

        # ~25 possessions per team per quarter = 50 total
        # Group into 12 "game-minutes"
        for gmin in range(12):
            poss_per_min = 4  # ~4 possessions per game-minute
            for poss in range(poss_per_min):
                parity = (gmin * poss_per_min + poss) % 2 == 0
                attacking = team_a if parity else team_b
                defending = team_b if parity else team_a
                run_ref = run_a if parity else run_b

                play_text, _, _ = _simulate_possession(attacking, defending, run_ref)
                plays.append(play_text)

            clock_mins = 11 - gmin
            clock_str = f"{clock_mins}:00"
            await push_update(q, clock_str)

        # End-of-quarter marker
        plays.append(
            f"**📣  END Q{q}  |  {team_a.owner}: {team_a.score}  —  {team_b.owner}: {team_b.score}**"
        )
        await push_update(q, "0:00")

    # ── Overtime ──────────────────────────────────────────────────────────────
    if team_a.score == team_b.score:
        overtime = True
        plays.append("\n🔥  **IT'S TIED — OVERTIME!**\n")
        await push_update(5, "5:00", ot=True)

        for gmin in range(5):
            for poss in range(4):
                parity = (gmin * 4 + poss) % 2 == 0
                attacking = team_a if parity else team_b
                defending = team_b if parity else team_a
                run_ref = run_a if parity else run_b
                play_text, _, _ = _simulate_possession(attacking, defending, run_ref)
                plays.append(play_text)

                # First score wins in OT
                if team_a.score != team_b.score:
                    break
            else:
                clock_str = f"{4 - gmin}:00"
                await push_update(5, clock_str, ot=True)
                continue
            break

        # If still tied after OT possessions, give random 2 pts to break
        if team_a.score == team_b.score:
            team_a.score += 2
            plays.append(f"🏀  Last-second bucket by {team_a.pg.short_name if team_a.pg else 'mystery player'}! (+2)")

    winner = team_a if team_a.score > team_b.score else team_b
    loser = team_b if winner is team_a else team_a

    w_stakes = stakes_a_text if winner is team_a else stakes_b_text
    l_stakes = stakes_b_text if winner is team_a else stakes_a_text

    final_embed = _build_final_embed(team_a, team_b, winner, loser, w_stakes, l_stakes, overtime)
    try:
        await message.edit(embed=final_embed)
    except Exception:
        pass

    return winner
