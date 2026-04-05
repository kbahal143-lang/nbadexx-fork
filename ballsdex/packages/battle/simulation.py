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

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

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
        weights = {"PG": 28, "SG": 22, "SF": 18, "PF": 17, "C": 15}
        pool: list[PlayerSim] = []
        for p in self.players():
            pool.extend([p] * weights.get(p.position, 10))
        return random.choice(pool)

    def pick_defender(self, attacker: PlayerSim) -> PlayerSim:
        weights = {}
        for p in self.players():
            if p.position == attacker.position:
                weights[p] = 40
            elif {p.position, attacker.position} <= {"PG", "SG"}:
                weights[p] = 25
            elif {p.position, attacker.position} <= {"SF", "PF"}:
                weights[p] = 25
            elif {p.position, attacker.position} <= {"PF", "C"}:
                weights[p] = 20
            else:
                weights[p] = 10
        pool: list[PlayerSim] = []
        for p, w in weights.items():
            pool.extend([p] * w)
        return random.choice(pool)

    def pick_rebounder(self) -> PlayerSim:
        weights = {"PG": 5, "SG": 8, "SF": 15, "PF": 28, "C": 35}
        pool: list[PlayerSim] = []
        for p in self.players():
            pool.extend([p] * weights.get(p.position, 10))
        return random.choice(pool)

    def pick_passer(self, scorer: PlayerSim) -> Optional[PlayerSim]:
        others = [p for p in self.players() if p is not scorer]
        if not others:
            return None
        weights = {"PG": 35, "SG": 20, "SF": 15, "PF": 15, "C": 15}
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
        "{a} attacks the rim with AUTHORITY",
        "{a} Euro-steps past the defender — FINISH!",
        "{a} with the finger roll — KISSED off the glass",
        "{a} goes BASELINE and throws it DOWN",
        "{a} catches the oop and HAMMERS it home",
        "{a} muscles through TWO defenders for the score",
        "{a} reverses it under the basket — INCREDIBLE",
        "{a} with the up-and-under — TOO SMOOTH",
        "{a} posterizes the defender — GROWN MAN MOVE",
        "{a} with the dream shake — UNSTOPPABLE",
        "{a} gets the and-one — THROUGH CONTACT!",
        "{a} windmill SLAMS it — ARE YOU KIDDING ME?!",
    ],
    "mid": [
        "{a} rises for the mid-range JUMPER",
        "{a} pulls up off the dribble",
        "{a} hits the floater over the defense",
        "{a} catches and fires from the elbow",
        "{a} drains the step-back mid-ranger",
        "{a} hits the turnaround jumper",
        "{a} isolates and nails the pull-up",
        "{a} fades away — NOTHING BUT NET",
        "{a} with the silky mid-range — WET",
        "{a} pulls up from the free throw line — AUTOMATIC",
        "{a} crosses over and DRAINS the mid-range",
        "{a} hits the spinning fadeaway — UNGUARDABLE",
        "{a} banks it in off the glass — CALCULATED",
        "{a} stops on a DIME — mid-range money",
        "{a} with the Dirk-style fadeaway — SPLASH",
        "{a} floats one in from the elbow — BUTTER",
        "{a} sinks the fadeaway baseline jumper",
        "{a} shakes the defender and BURIES it",
    ],
    "three": [
        "{a} fires from DOWNTOWN",
        "{a} steps back and lets it fly",
        "{a} catches and BOMBS the three",
        "{a} pulls up from deep — SPLASH",
        "{a} drains the corner THREE",
        "{a} launches from 30 feet",
        "{a} hits the step-back triple",
        "{a} DEEP THREE — BANG! BANG!",
        "{a} from WAY downtown — SWISH!",
        "{a} catches, shoots, SCORES from three",
        "{a} logo three — ARE YOU SERIOUS?!",
        "{a} shimmies and drains the three — ICE COLD",
        "{a} off the screen — BANG! It's GOOD!",
        "{a} heat check from deep — HE'S ON FIRE!",
        "{a} dances on the perimeter and NAILS IT",
        "{a} side-step THREE — COOKING!",
        "{a} from the PARKING LOT — BUCKET!",
        "{a} with the quick release — SNIPER!",
        "{a} LOGO THREE with a hand in his face — UNCONSCIOUS!",
        "{a} catches and fires in one motion — PURE!",
    ],
}

MISS_TEMPLATES = {
    "paint": [
        "{a} misses the layup — off the backboard",
        "{a} is rejected at the rim",
        "{a} throws the runner — rattles out",
        "{a} gets bodied at the rim — can't finish",
        "{a} loses it off the glass — no good",
        "{a} fumbles the layup — oh no!",
        "{a} gets stuffed at the basket",
        "{a} can't convert — the defense holds",
    ],
    "mid": [
        "{a} fires the mid-range — no good",
        "{a} misses the pull-up jumper",
        "{a} loses the ball on the fadeaway",
        "{a} clanks the mid-range off the rim",
        "{a} short on the elbow jumper",
        "{a} misses badly — way off the mark",
        "{a} forces the fadeaway — it bricks",
        "{a} rattles out the mid-range — tough shot",
    ],
    "three": [
        "{a} misses the three — long rebound",
        "{a} launches from deep — bricks it",
        "{a} fires off-balance — no good",
        "{a} air balls the three — YIKES",
        "{a} misses wide right from three",
        "{a} forces a contested three — WAY OFF",
        "{a} short on the three-ball — not even close",
        "{a} chucks it from deep — front rim",
    ],
}

STEAL_TEMPLATES = [
    "{d} picks the pocket of {a} — STEAL!",
    "{d} deflects the pass — STEAL!",
    "{d} anticipates the dribble — takes it away",
    "{d} jumps the passing lane for the STEAL",
    "{d} rips it RIGHT OUT of {a}'s hands!",
    "{d} reads the play perfectly — PICKPOCKET!",
    "{d} with the CLAMPS on {a} — stripped!",
    "{d} pokes it loose — ELITE defense!",
    "{d} intercepts the pass — {a} never saw it coming!",
    "{d} with the LOCKDOWN D — {a} coughs it up!",
]

BLOCK_TEMPLATES = [
    "{d} SWATS it into the third row — BLOCK!",
    "{d} rises and REJECTS {a} at the rim",
    "{d} sends it flying — massive BLOCK!",
    "{d} denies {a} completely at the basket",
    "{d} pins it against the BACKBOARD — GET THAT OUT!",
    "{d} says NOT IN MY HOUSE — REJECTED!",
    "{d} erases {a}'s shot — WALL OF DENIAL!",
    "{d} with the CHASE-DOWN block — INCREDIBLE!",
    "{d} VOLLEYBALL SPIKES {a}'s layup — DESTROYED!",
    "{d} times it PERFECTLY — {a} is sent packing!",
]

TO_TEMPLATES = [
    "{a} loses the handle — TURNOVER",
    "{a} dribbles off their own foot",
    "{a} throws it away out of bounds",
    "{a} commits a five-second violation",
    "{a} is called for a travel",
    "{a} steps out of bounds — sloppy!",
    "{a} forces a bad pass — picked off!",
    "{a} gets called for the offensive foul",
    "{a} bobbles it and loses possession",
    "{a} with a careless turnover — COSTLY mistake!",
]

FAST_BREAK_TEMPLATES = [
    "Fast break! {a} finishes in transition",
    "{a} takes it the length of the court",
    "{a} ahead of the defense for the AND-1",
    "{a} in transition — NO ONE CAN CATCH HIM!",
    "{a} on the fast break — EASY BUCKET!",
    "{a} coast to coast — EXPLOSIVE finish!",
]

FOUL_TEMPLATES = [
    "{d} hacks {a} — sends them to the line",
    "{d} commits a reach-in foul on {a}",
    "{a} draws the foul on {d}",
    "{d} wraps up {a} — can't let him score!",
    "{a} sells the contact — heading to the stripe",
    "{d} gets whistled for the foul on {a}",
]

RUN_TEMPLATES = [
    "{team} ON A RUN! The momentum is SHIFTING!",
    "{team} is ROLLING! Can anyone stop them?!",
    "{team} has caught FIRE! What a run!",
    "{team} is COOKING right now! UNSTOPPABLE!",
    "{team} is taking OVER! This is ELECTRIC!",
    "{team} REFUSES to miss! The crowd goes WILD!",
    "{team} is putting on a CLINIC right now!",
]

CLUTCH_TEMPLATES = [
    "CLUTCH shot by {a}! Ice in his veins!",
    "{a} delivers when it MATTERS MOST!",
    "{a} with the DAGGER — this one might be OVER!",
    "BIG TIME players make BIG TIME plays — {a}!",
    "{a} is BUILT for these moments!",
    "{a} — COLD BLOODED!",
]

HALFTIME_TEMPLATES = [
    "What a first half! Both teams came to PLAY!",
    "Halftime — the intensity is OFF THE CHARTS!",
    "We've got a BATTLE on our hands, folks!",
    "The first half was ELECTRIC — more to come!",
]

QUARTER_HYPE = {
    3: [
        "Second half BEGINS! Who wants it more?!",
        "Back from the break — time to TURN IT UP!",
        "The third quarter starts NOW — let's GO!",
    ],
    4: [
        "FOURTH QUARTER — this is where LEGENDS are made!",
        "The final quarter — EVERYTHING on the line!",
        "Crunch time! Who's going to step UP?!",
        "Q4 — no more warm-ups, this is FOR REAL!",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Core possession generator
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_possession(
    attacking: TeamSim,
    defending: TeamSim,
    run_length: list[int],
    is_clutch: bool = False,
) -> tuple[str, int, str]:
    attacker = attacking.pick_ball_handler()
    defender = defending.pick_defender(attacker)

    roll = random.random()

    diff = (defender.defense - attacker.offense)
    stl_chance = 0.08 * (1 + diff / 120)
    stl_chance = max(0.02, min(0.25, stl_chance))
    to_chance = 0.05 + max(0.0, diff / 500)
    to_chance = min(0.12, to_chance)
    if stl_chance + to_chance > 0.30:
        to_chance = 0.30 - stl_chance

    if roll < stl_chance:
        defender.stl += 1
        attacker.to += 1
        run_length[0] = 0
        template = random.choice(STEAL_TEMPLATES)
        text = template.format(a=attacker.short_name, d=defender.short_name)

        if random.random() < 0.35:
            fb_scorer = defending.pick_ball_handler()
            fb_tmpl = random.choice(FAST_BREAK_TEMPLATES)
            fb_text = fb_tmpl.format(a=fb_scorer.short_name)
            fb_scorer.pts += 2
            fb_scorer.fga += 1
            fb_scorer.fgm += 1
            defending.score += 2
            return f"🛡️ {text}\n⚡ {fb_text} (+2)", 2, "fastbreak"

        return f"🛡️ {text}", 0, "steal"

    if roll < stl_chance + to_chance:
        attacker.to += 1
        run_length[0] = 0
        template = random.choice(TO_TEMPLATES)
        text = template.format(a=attacker.short_name)
        return f"💨 {text}", 0, "to"

    foul_roll = random.random()
    if foul_roll < 0.08:
        atk_off_bonus = attacker.offense / 300
        ft_made = 0
        for _ in range(2):
            if random.random() < 0.60 + atk_off_bonus * 0.25:
                ft_made += 1
        attacker.fta += 2
        attacker.ftm += ft_made
        attacker.pts += ft_made
        attacking.score += ft_made
        template = random.choice(FOUL_TEMPLATES)
        text = template.format(a=attacker.short_name, d=defender.short_name)
        run_length[0] += ft_made
        return f"🆓 {text} — {ft_made}/2 FT", ft_made, "foul"

    dist_weights = POS_SHOT_DIST.get(attacker.position, POS_SHOT_DIST["SF"])
    r = random.random()
    if r < dist_weights["paint"]:
        shot_type = "paint"
    elif r < dist_weights["paint"] + dist_weights["mid"]:
        shot_type = "mid"
    else:
        shot_type = "three"

    pts_value = 3 if shot_type == "three" else 2

    off_rating = attacker.offense / 300
    def_rating = defender.defense / 300
    base_make = POS_BASE_MAKE[shot_type]
    stat_diff = off_rating - def_rating
    make_prob = base_make + stat_diff * 1.5
    make_prob = max(0.08, min(0.92, make_prob))

    attacker.fga += 1
    if shot_type == "three":
        attacker.tpa += 1

    if random.random() < make_prob:
        blk_chance = 0.03 + 0.08 * (defender.defense / 300) - 0.04 * (attacker.offense / 300)
        blk_chance = max(0.01, min(0.20, blk_chance))
        if random.random() < blk_chance and shot_type == "paint":
            defender.blk += 1
            blk_tmpl = random.choice(BLOCK_TEMPLATES)
            blk_text = blk_tmpl.format(a=attacker.short_name, d=defender.short_name)
            reb = defending.pick_rebounder()
            reb.reb += 1
            run_length[0] = 0
            return f"🧱 {blk_text} — {reb.short_name} with the reb", 0, "block"

        attacker.fgm += 1
        attacker.pts += pts_value
        attacking.score += pts_value
        if shot_type == "three":
            attacker.tpm += 1
        run_length[0] += pts_value

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
        elif shot_type == "paint" and ("SLAM" in text or "DUNK" in text or "HAMMER" in text):
            emoji = "💪"
        else:
            emoji = "🏀"

        run_str = ""
        if run_length[0] >= 6:
            run_tmpl = random.choice(RUN_TEMPLATES)
            run_str = f"\n🔥 {run_tmpl.format(team=attacking.owner)}"

        clutch_str = ""
        if is_clutch and pts_value >= 2 and random.random() < 0.4:
            clutch_tmpl = random.choice(CLUTCH_TEMPLATES)
            clutch_str = f"\n🧊 {clutch_tmpl.format(a=attacker.short_name)}"

        return f"{emoji} {text}{suffix}{run_str}{clutch_str}", pts_value, "make"

    else:
        run_length[0] = 0
        template = random.choice(MISS_TEMPLATES[shot_type])
        text = template.format(a=attacker.short_name)

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
    offense = inst.attack
    defense = inst.health
    special = inst.specialcard
    if special is not None:
        offense += getattr(special, "battle_atk_bonus", 0)
        defense += getattr(special, "battle_def_bonus", 0)
    return PlayerSim(
        name=inst.ball.country,
        position=position,
        offense=max(1, offense),
        defense=max(1, defense),
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


def _build_lineup_field(team: TeamSim, color_emoji: str) -> str:
    lines = []
    for p in team.players():
        lines.append(f"`{p.position}` **{p.name}** ({p.offense} OFF / {p.defense} HP)")
    return "\n".join(lines) if lines else "—"


def _build_live_embed(
    team_a: TeamSim,
    team_b: TeamSim,
    quarter: int,
    clock: str,
    plays: list[str],
    overtime: bool = False,
    show_lineups: bool = False,
) -> discord.Embed:
    if overtime:
        title = "🏀 OVERTIME"
        color = 0xFF6600
    else:
        title = f"🏀 LIVE  |  Q{quarter}  ·  {clock}"
        color = 0xE8501A

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="─── Score ───", value=_score_bar(team_a, team_b), inline=False)

    if show_lineups:
        embed.add_field(
            name=f"🟠 {team_a.owner}'s Lineup",
            value=_build_lineup_field(team_a, "🟠"),
            inline=True,
        )
        embed.add_field(
            name=f"🔵 {team_b.owner}'s Lineup",
            value=_build_lineup_field(team_b, "🔵"),
            inline=True,
        )

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

    a_stats = "\n".join(_fmt_player_stats(p) for p in team_a.players())
    embed.add_field(name=f"🟠  {team_a.owner}'s Stats", value=a_stats or "—", inline=False)

    b_stats = "\n".join(_fmt_player_stats(p) for p in team_b.players())
    embed.add_field(name=f"🔵  {team_b.owner}'s Stats", value=b_stats or "—", inline=False)

    winner_players = winner.players()
    if winner_players:
        mvp = max(winner_players, key=lambda p: p.pts)
        if mvp.pts > 0:
            embed.add_field(
                name="🏅  MVP",
                value=(
                    f"**{mvp.name}**  —  "
                    f"{mvp.pts} pts | {mvp.reb} reb | {mvp.ast} ast | "
                    f"{mvp.stl} stl | {mvp.blk} blk"
                ),
                inline=False,
            )

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
    plays: list[str] = []
    overtime = False

    run_a: list[int] = [0]
    run_b: list[int] = [0]

    async def push_update(quarter: int, clock: str, ot: bool = False, show_lineups: bool = False):
        try:
            embed = _build_live_embed(team_a, team_b, quarter, clock, plays, overtime=ot, show_lineups=show_lineups)
            await message.edit(embed=embed)
        except Exception:
            pass
        await asyncio.sleep(3)

    plays.append("**🏟️ LINEUP REVEAL — See lineups above!**")
    await push_update(1, "12:00", show_lineups=True)

    plays.clear()
    plays.append("🏀 **TIP OFF! Let's GO!**\n")
    await push_update(1, "12:00")

    for q in range(1, 5):
        plays.append(f"\n**━━  QUARTER {q}  ━━**\n")

        if q == 2:
            plays.append("📊 Second quarter — can they keep the pace?")
        elif q == 3:
            hype = random.choice(QUARTER_HYPE[3])
            plays.append(f"💥 {hype}")
        elif q == 4:
            hype = random.choice(QUARTER_HYPE[4])
            plays.append(f"⚡ {hype}")

        await push_update(q, "12:00")

        for gmin in range(12):
            poss_per_min = 4
            is_clutch = (q == 4 and gmin >= 9)

            for poss in range(poss_per_min):
                parity = (gmin * poss_per_min + poss) % 2 == 0
                attacking = team_a if parity else team_b
                defending = team_b if parity else team_a
                run_ref = run_a if parity else run_b

                play_text, _, _ = _simulate_possession(attacking, defending, run_ref, is_clutch=is_clutch)
                plays.append(play_text)

            clock_mins = 11 - gmin
            clock_str = f"{clock_mins}:00"
            await push_update(q, clock_str)

        plays.append(
            f"**📣  END Q{q}  |  {team_a.owner}: {team_a.score}  —  {team_b.owner}: {team_b.score}**"
        )

        if q == 2:
            ht = random.choice(HALFTIME_TEMPLATES)
            plays.append(f"\n🎤 **HALFTIME** — {ht}\n")
            diff = abs(team_a.score - team_b.score)
            if diff <= 3:
                plays.append("📊 A nail-biter! Only a few points separate these teams!")
            elif diff >= 15:
                leader = team_a.owner if team_a.score > team_b.score else team_b.owner
                plays.append(f"📊 {leader} is DOMINATING — can the other team come back?!")

        await push_update(q, "0:00")

    if team_a.score == team_b.score:
        overtime = True
        plays.append("\n🔥  **IT'S TIED — OVERTIME! WINNER TAKES ALL!**\n")
        await push_update(5, "5:00", ot=True)

        for gmin in range(5):
            for poss in range(4):
                parity = (gmin * 4 + poss) % 2 == 0
                attacking = team_a if parity else team_b
                defending = team_b if parity else team_a
                run_ref = run_a if parity else run_b
                play_text, _, _ = _simulate_possession(attacking, defending, run_ref, is_clutch=True)
                plays.append(play_text)

                if team_a.score != team_b.score:
                    break
            else:
                clock_str = f"{4 - gmin}:00"
                await push_update(5, clock_str, ot=True)
                continue
            break

        if team_a.score == team_b.score:
            lucky = random.choice([team_a, team_b])
            lucky.score += 2
            hero = lucky.pg or lucky.sg or lucky.sf or lucky.pf or lucky.c
            hero_name = hero.short_name if hero else "mystery player"
            plays.append(f"🏀  Last-second bucket by {hero_name} — BUZZER BEATER! (+2)")
            plays.append(f"🧊  {hero_name} is CLUTCH — what a way to end it!")

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
