"""Radio-broadcaster-style narrative engine for play-by-play text.

Generates varied, dramatic text for at-bats, inning transitions,
substitutions, and pinch hitter introductions. Templates use {batter}
and {pitcher} placeholders filled from NarrativeContext.
"""

import random
from dataclasses import dataclass
from typing import Dict, List

from src.game.state import BaseState, InningHalf
from src.simulation.engine import AtBatResult
from src.simulation.outcomes import AtBatOutcome


@dataclass(frozen=True)
class NarrativeContext:
    """Context for generating narrative text."""
    inning: int
    half: InningHalf
    outs: int
    base_state: BaseState
    away_score: int
    home_score: int
    batter_name: str
    pitcher_name: str
    batter_hits_today: int = 0
    pitcher_consecutive_retired: int = 0
    is_walkoff: bool = False
    inning_runs_scored: int = 0
    runs_on_play: int = 0


# --- Templates keyed by AtBatOutcome ---

_TEMPLATES: Dict[AtBatOutcome, List[str]] = {
    AtBatOutcome.HOME_RUN: [
        "{batter} drives one deep... it's out of here! Home run!",
        "{batter} sends one into the seats! Home run!",
        "{batter} connects and it's GONE!",
        "High fly ball, deep to left... that ball is OUTTA HERE! {batter} goes yard!",
        "{batter} crushes one! No doubt about it -- home run!",
        "A towering blast by {batter}! You can kiss that one goodbye!",
        "{batter} gets all of it! Way back... GONE!",
        "Off the bat of {batter} -- and that's a no-doubter! Home run!",
        "{batter} unloads on one! That ball is history!",
        "{batter} turns on it and launches it into the upper deck!",
        "Swing and a drive! {batter} puts one over the wall!",
    ],
    AtBatOutcome.STRIKEOUT_SWINGING: [
        "{batter} swings and misses! Strike three!",
        "He went after that one -- struck him out swinging!",
        "{batter} goes around on a breaking ball. Strikeout!",
        "Swinging strike three -- {batter} heads back to the dugout.",
        "{pitcher} paints the corner and {batter} chases. K!",
        "A big swing and a miss for {batter}. He's struck out.",
        "{batter} whiffs on the fastball. Strike three!",
        "That curveball got {batter}. Swing and a miss!",
        "{pitcher} blows one by {batter}. Strike three, swinging!",
        "Down goes {batter}! Caught swinging on a nasty slider.",
    ],
    AtBatOutcome.STRIKEOUT_LOOKING: [
        "Called strike three! {batter} caught looking!",
        "The umpire rings him up! {batter} watches strike three go by.",
        "{batter} takes a called third strike. He didn't agree with that one.",
        "Strike three, called! {batter} stood there frozen.",
        "{pitcher} catches the corner. Strike three looking!",
        "{batter} is rung up on a borderline pitch. Strikeout looking.",
        "That was right on the black. {batter} goes down looking.",
        "Punch him out! {batter} caught staring at strike three.",
        "{pitcher} freezes {batter} with a fastball. Called strike three!",
        "The ump calls it -- strike three! {batter} shakes his head.",
    ],
    AtBatOutcome.WALK: [
        "{batter} works a walk.",
        "Ball four -- {batter} takes his base.",
        "{pitcher} can't find the zone. Walk to {batter}.",
        "A base on balls for {batter}. Good eye at the plate.",
        "{batter} lays off the low one. That's a walk.",
        "Four balls and {batter} trots to first.",
        "{batter} shows patience and draws a free pass.",
        "That's ball four. {batter} earns a walk.",
        "{pitcher} walks {batter} on four pitches.",
        "A walk issued to {batter}. Runner aboard.",
    ],
    AtBatOutcome.HIT_BY_PITCH: [
        "{batter} is hit by the pitch! He'll take his base.",
        "Ouch! {pitcher} plunks {batter}. Take your base.",
        "{batter} gets clipped by a fastball. Hit by pitch.",
        "That one got away from {pitcher}. {batter} is awarded first base.",
        "{batter} can't get out of the way. Hit by pitch.",
        "Right in the ribs! {batter} takes first after being hit.",
        "{pitcher} loses one inside. {batter} wears it.",
        "{batter} gets drilled. He shakes it off and heads to first.",
        "The pitch tails in and catches {batter}. HBP.",
        "{batter} leans into one -- hit by pitch, take your base.",
    ],
    AtBatOutcome.SINGLE: [
        "{batter} lines one into the outfield for a base hit!",
        "A sharp single by {batter}!",
        "{batter} slaps one through the infield. Single!",
        "Base hit for {batter}! He ropes one into left.",
        "{batter} fights one off and drops it into right for a single.",
        "A clean single by {batter} up the middle.",
        "{batter} punches one through the hole. Base hit!",
        "Ground ball... through the infield! Single for {batter}!",
        "{batter} loops one over the shortstop. Base hit!",
        "A seeing-eye single by {batter}! Right through the gap.",
    ],
    AtBatOutcome.DOUBLE: [
        "{batter} rips one into the gap! He'll slide into second with a double!",
        "Line drive off the wall! {batter} hustles into second. Double!",
        "{batter} splits the outfielders! Stand-up double!",
        "A two-bagger for {batter}! Drilled into the corner!",
        "{batter} drives one deep -- off the wall for a double!",
        "Double! {batter} rattles one off the fence!",
        "{batter} smokes one down the line! It bounces off the wall -- double!",
        "A sharp grounder gets past the infielder. {batter} slides into second. Double!",
        "{batter} finds the gap in right-center. Two-base hit!",
        "What a shot by {batter}! That's a double into the corner!",
    ],
    AtBatOutcome.TRIPLE: [
        "{batter} drives one to the wall! He's heading for third -- triple!",
        "Way back... off the wall! {batter} legs out a triple!",
        "{batter} drills one to deep center! He's going to third!",
        "Triple! {batter} flies around the bases! Great speed!",
        "The ball rolls to the wall and {batter} is motoring! He'll make it to third!",
        "{batter} rockets one off the wall in right-center! Three-base hit!",
        "A screaming liner by {batter}! He's racing to third... SAFE! Triple!",
        "{batter} hits one over the outfielder's head! He'll coast into third!",
        "Blazing speed from {batter}! That's a triple!",
        "The outfielder can't run that one down! {batter} pulls into third with a triple!",
    ],
    AtBatOutcome.INFIELD_SINGLE: [
        "{batter} beats it out! Infield single!",
        "A chopper to short -- {batter} legs it out! Infield hit!",
        "{batter} hustles down the line and beats the throw! Infield single!",
        "That's a slow roller and {batter}'s speed gets him on. Infield hit!",
        "A swinging bunt by {batter} and he beats it out!",
        "{batter} chops one and uses his legs. Infield single!",
        "The throw is late! {batter} reaches on an infield single!",
        "A high bouncer to third -- {batter} beats the throw! Infield hit!",
        "{batter} puts one on the ground and outruns it! Single!",
        "Nubber to the mound -- {batter} is quick out of the box! Safe at first!",
    ],
    AtBatOutcome.GROUNDOUT: [
        "{batter} grounds out to short.",
        "Routine grounder -- {batter} is retired at first.",
        "{batter} bounces one to second. Easy out.",
        "Ground ball to third -- throw across the diamond. Out.",
        "{batter} chops one to the left side. They throw him out.",
        "A groundball to the right side retires {batter}.",
        "{batter} hits a one-hopper to the shortstop. Routine play, he's out.",
        "Tapper back to {pitcher}. Easy out at first.",
        "{batter} beats it into the ground. Fielded and thrown out at first.",
        "Ground ball to the second baseman -- flip to first. {batter} is out.",
    ],
    AtBatOutcome.FLYOUT: [
        "{batter} flies out to center.",
        "Fly ball to left -- caught for the out.",
        "{batter} lifts one to right field. Can of corn.",
        "A lazy fly ball to center. {batter} is retired.",
        "{batter} pops one up to the outfield. Easy play.",
        "Fly ball to left-center -- the outfielder runs it down. Out.",
        "{batter} skies one to right. Caught on the run.",
        "High fly ball... settling under it... caught! {batter} is out.",
        "A routine fly to left. {batter} heads back to the bench.",
        "{batter} gets under one and lifts it to the outfield. Caught.",
    ],
    AtBatOutcome.LINEOUT: [
        "{batter} lines out to the shortstop.",
        "Hard hit, but right at the second baseman. Lineout.",
        "{batter} smokes one, but it's caught! Liner right at the fielder.",
        "A screaming liner by {batter} -- but it's snared! What a catch!",
        "{batter} ropes one, but the third baseman snags it. Lineout.",
        "Hit hard but right at the outfielder. {batter} is robbed.",
        "A line shot by {batter} -- caught! Tough luck.",
        "Liner to center -- grabbed on the hop... no, caught! He's out!",
        "{batter} hits a rope to right, but the fielder barely has to move.",
        "Hard-hit ball, but right at somebody. {batter} is out on a liner.",
    ],
    AtBatOutcome.POPUP: [
        "{batter} pops up to the infield.",
        "Little popup behind second base. The shortstop drifts over. Out.",
        "{batter} skies one -- the catcher circles under it. Pop out.",
        "Infield fly! {batter} is automatically out.",
        "A high pop to the first baseman. {batter} is retired.",
        "{batter} gets under it too much. Easy popup to short.",
        "Pop fly on the infield. {batter} is out.",
        "{batter} pops one straight up. The catcher has it. Out.",
        "An infield popup. Nothing doing for {batter}.",
        "{batter} lofts a lazy pop. Caught by the second baseman.",
    ],
    AtBatOutcome.FOUL_OUT: [
        "{batter} fouls one off -- and it's caught! Foul out.",
        "Popup into foul territory -- the first baseman makes the grab!",
        "{batter} lifts one foul. The catcher tracks it down. Out.",
        "Foul ball down the line -- caught by the third baseman!",
        "{batter} chops one foul and the catcher snags it.",
        "A foul pop near the dugout -- nice grab! {batter} is out.",
        "Foul ball! The fielder drifts over... makes the catch!",
        "{batter} pops one foul. The catcher camps under it. Out.",
        "Foul fly to the first base side -- caught! {batter} is retired.",
        "That's in foul ground... but it's caught! Out for {batter}.",
    ],
    AtBatOutcome.REACHED_ON_ERROR: [
        "{batter} reaches on an error!",
        "That's an error! {batter} is aboard!",
        "The fielder boots it -- {batter} reaches on the miscue!",
        "Error on the play! {batter} reaches safely.",
        "Bobbled! {batter} takes advantage of the error.",
        "An E-6! The shortstop can't handle it. {batter} is safe.",
        "The throw pulls the first baseman off the bag! Error! {batter} reaches.",
        "{batter} hits a routine grounder... but it's booted! Error!",
        "Wild throw! {batter} reaches on the error!",
        "The fielder had it and let it slip. Error! {batter} is on.",
    ],
    AtBatOutcome.SACRIFICE_FLY: [
        "{batter} lifts a sacrifice fly. The runner tags and scores!",
        "Fly ball deep enough -- sac fly by {batter}! Run scores!",
        "{batter} puts it in the air. The runner tags up. Sacrifice fly!",
        "A productive out for {batter} -- sac fly scores the runner!",
        "Deep enough! The runner tags from third. Sacrifice fly for {batter}.",
        "{batter} gets it out there far enough. The run comes in on the sac fly.",
        "Fly ball to right -- the runner tags. Sacrifice fly by {batter}!",
        "{batter} gives himself up. Sac fly -- the runner trots home.",
        "A sacrifice fly to center brings home the run. {batter} does the job.",
        "Tag up! The runner scores on {batter}'s sacrifice fly!",
    ],
    AtBatOutcome.SACRIFICE_HIT: [
        "{batter} lays down a sacrifice bunt. Runners advance!",
        "A textbook sac bunt by {batter}. He's out, but the runners move up.",
        "{batter} squares around and drops one down the line. Sacrifice!",
        "Bunt! {batter} gives himself up to advance the runners.",
        "{batter} puts down a sacrifice. Small ball at its finest.",
        "A perfect bunt by {batter}. The runners advance on the sacrifice.",
        "{batter} bunts one toward first. Out at first, but the runners advance.",
        "The sacrifice bunt is down. {batter} is thrown out, runners move up.",
        "{batter} lays it down beautifully. Sacrifice bunt.",
        "A well-placed bunt by {batter}. He's out, runners advance.",
    ],
    AtBatOutcome.GIDP: [
        "{batter} hits into a double play! Two down on that one.",
        "Ground ball to short -- 6-4-3 double play! {batter} grounds into two.",
        "That's a twin killing! {batter} hits into a GIDP.",
        "Double play ball! {batter} grounds into the 4-6-3.",
        "{batter} rolls one to second -- turn two! Double play!",
        "The pitcher's best friend -- a double play ball from {batter}.",
        "{batter} bounces into a rally-killing double play.",
        "There's the double play! {batter} kills the rally.",
        "Groundball -- pivot -- throw! Double play! {batter} grounds into two.",
        "6-3 double play! {batter} hits it right at the shortstop.",
    ],
    AtBatOutcome.FIELD_CHOICE: [
        "{batter} reaches on a fielder's choice. The runner is thrown out.",
        "Fielder's choice -- they get the lead runner. {batter} is safe at first.",
        "Ground ball, they go to second for the force. {batter} reaches on the FC.",
        "{batter} puts it on the ground -- fielder's choice. Runner out at second.",
        "The defense opts for the lead runner. Fielder's choice for {batter}.",
        "Force out at second. {batter} reaches on the fielder's choice.",
        "{batter} grounds into a fielder's choice. They retire the lead runner.",
        "A grounder to short -- they get the force at second. {batter} is safe.",
        "Fielder's choice at second base. {batter} beats the relay to first.",
        "The play goes to second for the force out. {batter} on via fielder's choice.",
    ],
}


_INNING_ORDINALS = {
    1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
    7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th",
    13: "13th", 14: "14th", 15: "15th",
}

_SUBSTITUTION_TEMPLATES = [
    "The skipper's seen enough -- here comes the hook. {new_pitcher} takes the mound for {team_name}.",
    "That's it for {old_pitcher}. {new_pitcher} will take over on the hill.",
    "Pitching change: {new_pitcher} coming in to replace {old_pitcher} for {team_name}.",
    "The manager signals to the bullpen. {new_pitcher} is on his way in for {team_name}.",
    "{old_pitcher}'s day is done. {new_pitcher} will try to hold things down for {team_name}.",
    "Here comes {new_pitcher} out of the pen. {old_pitcher} tips his cap as he heads off.",
    "The bullpen door swings open. {new_pitcher} makes the long walk in for {team_name}.",
]

_PINCH_HITTER_TEMPLATES = [
    "Now batting for {replaced_batter}... {pinch_hitter}!",
    "Here comes {pinch_hitter}, pinch-hitting for {replaced_batter}. The crowd stirs.",
    "{team_name} making a move -- {pinch_hitter} grabs a bat and heads to the plate for {replaced_batter}.",
    "The skipper's going to his bench. {pinch_hitter} will bat for {replaced_batter}.",
    "{pinch_hitter} steps into the box as the pinch hitter. {replaced_batter} heads back to the dugout.",
    "A pinch hitter is announced: {pinch_hitter} batting for {replaced_batter}.",
    "{pinch_hitter} emerges from the dugout. He'll hit for {replaced_batter}.",
]

_INNING_SUMMARY_SCORELESS = [
    "{team_name} go down quietly in the {ordinal}.",
    "A scoreless {ordinal} for {team_name}.",
    "Nothing doing for {team_name} in the {ordinal}.",
    "{team_name} are retired in order in the {ordinal}.",
]

_INNING_SUMMARY_RUNS = [
    "{team_name} put up {runs} in the {ordinal}.",
    "{runs} run{'s' if {runs} != 1 else ''} cross{'es' if {runs} == 1 else ''} the plate for {team_name} in the {ordinal}.",
    "{team_name} score {runs} in the {ordinal}.",
]

_INNING_SUMMARY_BIG = [
    "A {runs}-run {ordinal} for {team_name}!",
    "{team_name} break it open with {runs} runs in the {ordinal}!",
    "What an inning! {runs} runs for {team_name} in the {ordinal}!",
]

_RUNS_SCORED_SUFFIXES = [
    " {count} run{s} score{verb}!",
]


def _ordinal(inning: int) -> str:
    return _INNING_ORDINALS.get(inning, f"{inning}th")


def _runs_suffix(count: int) -> str:
    if count == 0:
        return ""
    if count == 1:
        return " A run scores!"
    return f" {count} runs score!"


def generate_play_text(result: AtBatResult, ctx: NarrativeContext) -> str:
    """Generate broadcaster-style narrative for an at-bat result.

    Args:
        result: The at-bat outcome and stats.
        ctx: Current game context for situational text.

    Returns:
        Narrative string with {batter}/{pitcher} filled in.
    """
    templates = _TEMPLATES.get(result.outcome)
    if not templates:
        return f"{ctx.batter_name}: {result.outcome.name.replace('_', ' ').title()}"

    text = random.choice(templates).format(batter=ctx.batter_name, pitcher=ctx.pitcher_name)

    # Runs scored suffix (only for non-HR since HR text is self-explanatory)
    if ctx.runs_on_play > 0 and result.outcome != AtBatOutcome.HOME_RUN:
        text += _runs_suffix(ctx.runs_on_play)

    # Walk-off
    if ctx.is_walkoff:
        text += " Walk-off! What a finish!"

    # Clutch: 2 outs, runners on, score within 1
    score_diff = abs(ctx.away_score - ctx.home_score)
    has_runners = ctx.base_state.first or ctx.base_state.second or ctx.base_state.third
    if ctx.outs == 2 and has_runners and score_diff <= 1 and not ctx.is_walkoff:
        if result.outcome.is_hit:
            text += " What a spot!"

    # Streak
    if ctx.batter_hits_today >= 3 and result.outcome.is_hit:
        text += f" That's his {ctx.batter_hits_today + 1}th hit today!"

    # Pitcher dominance
    if ctx.pitcher_consecutive_retired >= 10 and result.outcome.is_out:
        text += f" {ctx.pitcher_name} has now retired {ctx.pitcher_consecutive_retired + 1} straight."

    return text


def generate_inning_summary(team_name: str, runs: int, inning: int, half: InningHalf) -> str:
    """Generate inning transition narrative.

    Args:
        team_name: Name of the team that just batted.
        runs: Runs scored in the half-inning.
        inning: Inning number.
        half: Which half of the inning.

    Returns:
        Summary text for the inning transition.
    """
    ordinal = _ordinal(inning)

    if runs == 0:
        return random.choice(_INNING_SUMMARY_SCORELESS).format(
            team_name=team_name, ordinal=ordinal
        )
    elif runs >= 4:
        return random.choice(_INNING_SUMMARY_BIG).format(
            team_name=team_name, runs=runs, ordinal=ordinal
        )
    else:
        # Simple runs summary
        if runs == 1:
            return f"{team_name} push across a run in the {ordinal}."
        return f"{team_name} score {runs} in the {ordinal}."


def generate_substitution_text(old_pitcher: str, new_pitcher: str, team_name: str) -> str:
    """Generate dramatic pitcher change narrative.

    Args:
        old_pitcher: Name of pitcher being replaced.
        new_pitcher: Name of replacement pitcher.
        team_name: Team making the change.

    Returns:
        Narrative text for the pitching change.
    """
    return random.choice(_SUBSTITUTION_TEMPLATES).format(
        old_pitcher=old_pitcher, new_pitcher=new_pitcher, team_name=team_name
    )


def generate_pinch_hitter_text(pinch_hitter: str, replaced_batter: str, team_name: str) -> str:
    """Generate dramatic pinch hitter introduction.

    Args:
        pinch_hitter: Name of the pinch hitter.
        replaced_batter: Name of the batter being replaced.
        team_name: Team making the move.

    Returns:
        Narrative text for the pinch hitter announcement.
    """
    return random.choice(_PINCH_HITTER_TEMPLATES).format(
        pinch_hitter=pinch_hitter, replaced_batter=replaced_batter, team_name=team_name
    )
