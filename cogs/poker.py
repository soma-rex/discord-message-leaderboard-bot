import random
import time
from collections import Counter
from itertools import combinations

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
CHIP_EMOJI  = "<:poker_chip:1487837444685430896>"
SPADE_EMOJI = "<:spade:1487837442907050197>"
HEART_EMOJI = "<:heart:1487837441535508591>"
DIAM_EMOJI  = "<:diamond:1487837439967105075>"
CLUB_EMOJI  = "<:club:1487837438083862698>"

SUITS      = ["♠", "♥", "♦", "♣"]
RANKS      = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

SUIT_EMOJI = {
    "♠": SPADE_EMOJI,
    "♥": HEART_EMOJI,
    "♦": DIAM_EMOJI,
    "♣": CLUB_EMOJI,
}

def format_card(card: str) -> str:
    rank = card[:-1]
    suit = card[-1]
    return f"**{rank}**{SUIT_EMOJI.get(suit, suit)}"

def format_cards(cards: list) -> str:
    return "  ".join(format_card(c) for c in cards)

HAND_NAMES = {
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "One Pair",
    0: "High Card",
}

PHASE_COLORS = {
    "preflop":  discord.Color.blurple(),
    "flop":     discord.Color.blue(),
    "turn":     discord.Color.orange(),
    "river":    discord.Color.red(),
    "showdown": discord.Color.gold(),
}

TABLE_PRESETS = {
    "high_rollers": {
        "name": "Dragon's Vault",
        "buy_in": 10000,
        "raise_cap": 5000,
    },
    "low_stakes": {
        "name": "Firefly Den",
        "buy_in": 1000,
        "raise_cap": 500,
    },
}

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == 720550790036455444


# ─────────────────────────────────────────────
# DECK HELPERS
# ─────────────────────────────────────────────
def build_deck():
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck

def card_rank(card: str) -> str:
    return card[:-1]

def card_suit(card: str) -> str:
    return card[-1]


# ─────────────────────────────────────────────
# HAND EVALUATOR
# ─────────────────────────────────────────────
def _score_five(cards):
    ranks  = [card_rank(c) for c in cards]
    suits  = [card_suit(c) for c in cards]
    vals   = sorted([RANK_VALUE[r] for r in ranks], reverse=True)
    counts = Counter(ranks)
    freq   = sorted(counts.values(), reverse=True)

    is_flush    = len(set(suits)) == 1
    is_straight = len(set(vals)) == 5 and vals[0] - vals[4] == 4
    if set(vals) == {14, 2, 3, 4, 5}:
        is_straight = True
        vals = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return (8, vals)
    if freq[0] == 4:
        quad_rank = next(r for r, c in counts.items() if c == 4)
        quad_val  = RANK_VALUE[quad_rank]
        kickers   = sorted([RANK_VALUE[r] for r in ranks if r != quad_rank], reverse=True)
        return (7, [quad_val] + kickers)
    if freq[0] == 3 and freq[1] == 2:
        trip_rank = next(r for r, c in counts.items() if c == 3)
        pair_rank = next(r for r, c in counts.items() if c == 2)
        return (6, [RANK_VALUE[trip_rank], RANK_VALUE[pair_rank]])
    if is_flush:
        return (5, vals)
    if is_straight:
        return (4, vals)
    if freq[0] == 3:
        trip_rank = next(r for r, c in counts.items() if c == 3)
        kickers   = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 1], reverse=True)
        return (3, [RANK_VALUE[trip_rank]] + kickers)
    if freq[0] == 2 and freq[1] == 2:
        pair_ranks = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 2], reverse=True)
        kicker     = max(RANK_VALUE[r] for r, c in counts.items() if c == 1)
        return (2, pair_ranks + [kicker])
    if freq[0] == 2:
        pair_rank = next(r for r, c in counts.items() if c == 2)
        kickers   = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 1], reverse=True)
        return (1, [RANK_VALUE[pair_rank]] + kickers)
    return (0, vals)

def evaluate_hand(cards: list) -> tuple:
    if len(cards) <= 5:
        return _score_five(cards)
    return max(_score_five(list(combo)) for combo in combinations(cards, 5))

def hand_name(score_tuple: tuple) -> str:
    return HAND_NAMES.get(score_tuple[0], "Unknown")


# ─────────────────────────────────────────────
# SIDE POTS
# ─────────────────────────────────────────────
def build_side_pots(game: dict) -> list:
    players = game["players"]
    contributions = {
        uid: p["total_chip_in"]
        for uid, p in players.items()
        if p["total_chip_in"] > 0
    }
    pots = []
    while contributions:
        min_in   = min(contributions.values())
        involved = list(contributions.keys())
        pot_amount = min_in * len(involved)
        eligible   = [uid for uid in involved if not players[uid]["folded"]]
        if eligible:
            pots.append({"amount": pot_amount, "eligible": eligible})
        contributions = {uid: amt - min_in for uid, amt in contributions.items() if amt - min_in > 0}
    return pots


# ─────────────────────────────────────────────
# EMBED BUILDERS
# ─────────────────────────────────────────────
def build_game_embed(game: dict) -> discord.Embed:
    phase       = game["phase"].title()
    current_uid = game["player_order"][game["turn_index"]]
    board       = format_cards(game["visible_community"]) if game["visible_community"] else "*(cards hidden)*"
    color       = PHASE_COLORS.get(game["phase"], discord.Color.blurple())
    embed = discord.Embed(
        title=f"{SPADE_EMOJI} {HEART_EMOJI}  Texas Hold'em  ·  {phase}  {DIAM_EMOJI} {CLUB_EMOJI}",
        color=color,
    )
    embed.add_field(name="🃏  Board",          value=board,                          inline=False)
    embed.add_field(name=f"{CHIP_EMOJI}  Pot", value=f"**{game['pot']}**",          inline=True)
    embed.add_field(name="📊  Current bet",    value=f"**{game['current_bet']}**",  inline=True)
    embed.add_field(name="🎯  Acting",         value=f"<@{current_uid}>",           inline=True)
    embed.set_footer(text='Press "Players" to see everyone\'s status')
    return embed


def build_players_embed(game: dict) -> discord.Embed:
    current_uid = game["player_order"][game["turn_index"]]
    embed = discord.Embed(title="👥  Players at the table", color=discord.Color.dark_grey())
    lines = []
    for uid in game["player_order"]:
        p = game["players"][uid]
        if p["folded"]:
            icon, note = "❌", "folded"
        elif p.get("all_in"):
            icon, note = "💥", f"all-in  (total in: {p['total_chip_in']})"
        else:
            icon, note = "🟢", f"bet {p['bet']}"
        turn = "  ◀ **their turn**" if uid == current_uid else ""
        lines.append(f"{icon}  <@{uid}>  —  {note}{turn}")
    embed.description = "\n".join(lines)
    return embed


class RaiseModal(discord.ui.Modal, title="Custom Raise"):
    raise_amount = discord.ui.TextInput(
        label="Raise amount",
        placeholder="Enter how much to raise by",
        required=True,
        max_length=5,
    )

    def __init__(self, view: "PokerBetView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        game, player, err = self.view._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        raw_amount = str(self.raise_amount).strip()
        if not raw_amount.isdigit():
            await interaction.response.send_message("Raise amount must be a whole number.", ephemeral=True)
            return

        raise_by = int(raw_amount)
        raise_cap = game["raise_cap"]
        if raise_by <= 0:
            await interaction.response.send_message("Raise amount must be greater than 0.", ephemeral=True)
            return
        if raise_by > raise_cap:
            await interaction.response.send_message(
                f"This table only allows raises up to **{raise_cap}** per turn.",
                ephemeral=True,
            )
            return

        target = game["current_bet"] + raise_by
        amount = target - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Invalid raise amount.", ephemeral=True)
            return
        if not self.view.cog.remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips - try All-In.", ephemeral=True)
            return

        game["current_bet"] = target
        player["bet"] = target
        player["total_chip_in"] += amount
        game["pot"] += amount
        player["acted"] = True

        for uid, other in game["players"].items():
            if uid != interaction.user.id and not other["folded"] and not other.get("all_in"):
                other["acted"] = False

        self.view._advance_turn_index(game)
        await interaction.response.send_message(
            f"Raised by **{raise_by}** to **{target}**.",
            ephemeral=True,
        )
        await self.view._announce_action(
            interaction.channel,
            interaction.user,
            f"raised by **{raise_by}** to **{target}**.",
        )
        await self.view.resolve_turn(interaction.channel)


# ─────────────────────────────────────────────
# SHOWDOWN
# ─────────────────────────────────────────────
async def finish_poker_game(channel: discord.TextChannel, game: dict, cog: "PokerCog"):
    players = game["players"]
    game["visible_community"] = game["community"][:]

    pots          = build_side_pots(game)
    results_lines = []
    total_awarded = 0

    for i, pot in enumerate(pots):
        eligible = pot["eligible"]
        if not eligible:
            continue

        scored = []
        for uid in eligible:
            score = evaluate_hand(players[uid]["cards"] + game["community"])
            scored.append((score, uid, players[uid]["cards"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score = scored[0][0]
        winners    = [s for s in scored if s[0] == best_score]
        split      = pot["amount"] // len(winners)
        remainder  = pot["amount"] % len(winners)
        total_awarded += pot["amount"]

        for idx, (_, uid, _) in enumerate(winners):
            cog.add_chips(uid, split + (remainder if idx == 0 else 0))

        winner_names = []
        for _, uid, _ in winners:
            try:
                m = await channel.guild.fetch_member(uid)
                winner_names.append(m.display_name)
            except Exception:
                winner_names.append(f"<@{uid}>")

        label = f"Side pot {i+1}" if len(pots) > 1 else "Main pot"
        results_lines.append(f"**{label}  ({pot['amount']} chips)** → {', '.join(winner_names)}")

    # Safety net: if pot math left chips unawarded, give to first pot winner
    if total_awarded < game["pot"] and pots and pots[0]["eligible"]:
        cog.add_chips(pots[0]["eligible"][0], game["pot"] - total_awarded)

    hand_lines = []
    for uid, data in players.items():
        if data["folded"]:
            continue
        score = evaluate_hand(data["cards"] + game["community"])
        try:
            m    = await channel.guild.fetch_member(uid)
            name = m.display_name
        except Exception:
            name = f"<@{uid}>"
        hand_lines.append(f"**{name}** — {format_cards(data['cards'])}  ·  *{hand_name(score)}*")

    embed = discord.Embed(title="🏆  Showdown!", color=discord.Color.gold())
    embed.add_field(name="🃏  Board",      value=format_cards(game["community"]) or "—", inline=False)
    embed.add_field(name="🥇  Results",   value="\n".join(results_lines) or "—",         inline=False)
    embed.add_field(name="🂠  All Hands", value="\n".join(hand_lines)    or "—",          inline=False)

    await channel.send(embed=embed)
    if channel.id in cog.poker_games:
        del cog.poker_games[channel.id]


# ─────────────────────────────────────────────
# HELPER: find next player who can act
# ─────────────────────────────────────────────
def _next_actor(game: dict, from_index: int):
    n = len(game["player_order"])
    for i in range(1, n + 1):
        nxt = (from_index + i) % n
        uid = game["player_order"][nxt]
        p   = game["players"][uid]
        if not p["folded"] and not p.get("all_in"):
            return nxt
    return None


# ─────────────────────────────────────────────
# BETTING VIEW
# ─────────────────────────────────────────────
class PokerBetView(discord.ui.View):
    def __init__(self, channel_id: int, game: dict, cog: "PokerCog"):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.game       = game
        self.cog        = cog

    async def on_timeout(self):
        game = self.cog.poker_games.get(self.channel_id)
        if not game:
            return

        current_uid = game["player_order"][game["turn_index"]]
        player      = game["players"].get(current_uid)

        if player and not player["folded"] and not player.get("all_in"):
            player["folded"] = True
            player["acted"]  = True

        nxt = _next_actor(game, game["turn_index"])
        if nxt is not None:
            game["turn_index"] = nxt

        try:
            channel = self.cog.bot.get_channel(self.channel_id)
            if not channel:
                return

            alive = [uid for uid, p in game["players"].items() if not p["folded"]]

            if len(alive) <= 1:
                if alive:
                    winner_id = alive[0]
                    self.cog.add_chips(winner_id, game["pot"])
                    try:
                        m    = await channel.guild.fetch_member(winner_id)
                        name = m.display_name
                    except Exception:
                        name = f"<@{winner_id}>"
                    embed = discord.Embed(
                        title="🏆  Game over (timeout)",
                        description=(
                            f"<@{current_uid}> took too long and was auto-folded.\n"
                            f"**{name}** wins **{game['pot']}** {CHIP_EMOJI}!"
                        ),
                        color=discord.Color.gold(),
                    )
                    await channel.send(embed=embed)
                if self.channel_id in self.cog.poker_games:
                    del self.cog.poker_games[self.channel_id]
                return

            notice = discord.Embed(
                description=f"⏱️  <@{current_uid}> took too long and was auto-folded.",
                color=discord.Color.orange(),
            )
            await channel.send(embed=notice)

            can_act    = [p for p in game["players"].values() if not p["folded"] and not p.get("all_in")]
            bets_level = all(p["bet"] == game["current_bet"] for p in can_act) if can_act else True
            all_acted  = all(p["acted"] for p in can_act) if can_act else True

            dummy_view = PokerBetView(self.channel_id, game, self.cog)
            if (not can_act) or (all_acted and bets_level):
                await dummy_view.advance_phase(channel)
            else:
                next_uid = game["player_order"][game["turn_index"]]
                new_view = PokerBetView(self.channel_id, game, self.cog)
                embed    = build_game_embed(game)
                await channel.send(f"<@{next_uid}>", embed=embed, view=new_view)

        except Exception:
            if self.channel_id in self.cog.poker_games:
                del self.cog.poker_games[self.channel_id]

    def get_game(self):
        return self.cog.poker_games.get(self.channel_id)

    def _guard(self, interaction: discord.Interaction):
        game = self.get_game()
        if not game:
            return None, None, "No active game."
        current = game["player_order"][game["turn_index"]]
        if interaction.user.id != current:
            return game, None, "It's not your turn."
        player = game["players"].get(interaction.user.id)
        if not player or player["folded"]:
            return game, None, "You're not active in this hand."
        if player.get("all_in"):
            return game, None, "You are all-in — nothing to do."
        if player["acted"]:
            return game, None, "You already acted this round."
        return game, player, None

    def _advance_turn_index(self, game: dict):
        nxt = _next_actor(game, game["turn_index"])
        if nxt is not None:
            game["turn_index"] = nxt

    async def _announce_action(self, channel: discord.TextChannel, user: discord.Member, action: str):
        embed = discord.Embed(
            description=f"**{user.display_name}** {action}",
            color=discord.Color.dark_grey(),
        )
        await channel.send(embed=embed)

    async def advance_phase(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        phases = ["preflop", "flop", "turn", "river", "showdown"]
        idx    = phases.index(game["phase"])
        game["phase"] = phases[idx + 1]

        if game["phase"] == "flop":
            game["visible_community"] = game["community"][:3]
        elif game["phase"] == "turn":
            game["visible_community"] = game["community"][:4]
        elif game["phase"] == "river":
            game["visible_community"] = game["community"][:5]
        elif game["phase"] == "showdown":
            await finish_poker_game(channel, game, self.cog)
            return

        # Reset street bets
        game["current_bet"] = 0
        for p in game["players"].values():
            p["bet"] = 0
            if not p["folded"] and not p.get("all_in"):
                p["acted"] = False

        can_act = [uid for uid, p in game["players"].items()
                   if not p["folded"] and not p.get("all_in")]

        # If 0 or 1 players can act, keep advancing through phases
        # (board cards are revealed above before this check, so they always show)
        if len(can_act) <= 1:
            await self.advance_phase(channel)
            return

        game["turn_index"] = game["player_order"].index(can_act[0])
        current_uid = game["player_order"][game["turn_index"]]
        new_view    = PokerBetView(self.channel_id, game, self.cog)
        embed       = build_game_embed(game)
        await channel.send(f"<@{current_uid}>", embed=embed, view=new_view)

    async def resolve_turn(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        # Only one player left standing
        alive_users = [uid for uid, p in game["players"].items() if not p["folded"]]
        if len(alive_users) == 1:
            winner_id = alive_users[0]
            self.cog.add_chips(winner_id, game["pot"])
            try:
                m    = await channel.guild.fetch_member(winner_id)
                name = m.display_name
            except Exception:
                name = f"<@{winner_id}>"
            embed = discord.Embed(
                title=f"🏆  {name} wins!",
                description=f"Everyone else folded.\n{CHIP_EMOJI} **{game['pot']} chips** awarded.",
                color=discord.Color.gold(),
            )
            await channel.send(embed=embed)
            del self.cog.poker_games[self.channel_id]
            return

        can_act    = [p for p in game["players"].values() if not p["folded"] and not p.get("all_in")]
        bets_level = all(p["bet"] == game["current_bet"] for p in can_act) if can_act else True
        all_acted  = all(p["acted"] for p in can_act) if can_act else True

        if (not can_act) or (all_acted and bets_level):
            await self.advance_phase(channel)
            return

        current_uid = game["player_order"][game["turn_index"]]
        new_view    = PokerBetView(self.channel_id, game, self.cog)
        embed       = build_game_embed(game)
        await channel.send(f"<@{current_uid}>", embed=embed, view=new_view)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger, row=0)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        player["folded"] = True
        player["acted"]  = True
        self._advance_turn_index(game)
        await interaction.response.send_message("❌ You folded.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, "folded.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Check", style=discord.ButtonStyle.secondary, row=0)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        if game["current_bet"] != player["bet"]:
            await interaction.response.send_message(
                f"Can't check — there is a bet of **{game['current_bet']}**. Call or raise.",
                ephemeral=True,
            )
            return
        player["acted"] = True
        self._advance_turn_index(game)
        await interaction.response.send_message("✅ Checked.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, "checked.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Call", style=discord.ButtonStyle.primary, row=0)
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        amount = game["current_bet"] - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Nothing to call — use Check.", ephemeral=True)
            return

        chips = self.cog.get_chips(interaction.user.id)

        if chips <= 0:
            player["all_in"] = True
            player["acted"]  = True
            self._advance_turn_index(game)
            await interaction.response.send_message("💥 You're all-in (no chips left)!", ephemeral=True)
            await self._announce_action(interaction.channel, interaction.user, "is **all-in**.")
            await self.resolve_turn(interaction.channel)
            return

        if chips < amount:
            amount           = chips
            player["all_in"] = True

        self.cog.remove_chips(interaction.user.id, amount)
        player["bet"]           += amount
        player["total_chip_in"] += amount
        game["pot"]             += amount
        player["acted"]          = True
        self._advance_turn_index(game)

        suffix = "  *(All-in!)*" if player.get("all_in") else ""
        await interaction.response.send_message(f"☎️ Called **{amount}**.{suffix}", ephemeral=True)
        if player.get("all_in"):
            await self._announce_action(
                interaction.channel,
                interaction.user,
                f"called **{amount}** and is now **all-in**.",
            )
        else:
            await self._announce_action(interaction.channel, interaction.user, f"called **{amount}**.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Custom Raise", style=discord.ButtonStyle.success, row=1)
    async def raise_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        modal = RaiseModal(self)
        modal.raise_amount.placeholder = f"Max {game['raise_cap']} on this table"
        await interaction.response.send_modal(modal)
        return
        target = game["current_bet"] + 100
        amount = target - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Invalid raise amount.", ephemeral=True)
            return
        if not self.cog.remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips — try All-In.", ephemeral=True)
            return
        game["current_bet"]     = target
        player["bet"]           = target
        player["total_chip_in"] += amount
        game["pot"]             += amount
        player["acted"]          = True
        for uid, p in game["players"].items():
            if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                p["acted"] = False
        self._advance_turn_index(game)
        await interaction.response.send_message(f"📈 Raised to **{target}**.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, f"raised to **{target}**.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="All-In 💥", style=discord.ButtonStyle.danger, row=1)
    async def all_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        chips = self.cog.get_chips(interaction.user.id)
        if chips > 0:
            self.cog.remove_chips(interaction.user.id, chips)
            player["bet"]           += chips
            player["total_chip_in"] += chips
            game["pot"]             += chips
        player["all_in"] = True
        player["acted"]  = True
        if player["bet"] > game["current_bet"]:
            game["current_bet"] = player["bet"]
            for uid, p in game["players"].items():
                if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                    p["acted"] = False
        self._advance_turn_index(game)
        msg = f"💥 All-in with **{chips}** chips!" if chips > 0 else "💥 You're all-in!"
        await interaction.response.send_message(msg, ephemeral=True)
        if chips > 0:
            await self._announce_action(
                interaction.channel,
                interaction.user,
                f"went **all-in** with **{chips}** chips.",
            )
        else:
            await self._announce_action(interaction.channel, interaction.user, "is **all-in**.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="👥 Players", style=discord.ButtonStyle.secondary, row=1)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        if not game:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_players_embed(game), ephemeral=True)


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class PokerCog(commands.Cog, ChipsMixin, name="Poker"):
    """Texas Hold'em poker with chips."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.poker_games: dict = {}
        self.conn        = bot.conn
        self.cursor      = bot.cursor
        self._ensure_chip_table()

    def _ensure_table(self):
        self._ensure_chip_table()

    poker_group = app_commands.Group(name="poker", description="Texas Hold'em with chips")

    @app_commands.command(name="daily", description="Claim your daily poker chips")
    async def daily(self, interaction: discord.Interaction):
        self.ensure_chips(interaction.user.id)
        self.cursor.execute(
            "SELECT last_daily FROM poker_chips WHERE user_id = ?", (interaction.user.id,)
        )
        last_daily = self.cursor.fetchone()[0]
        now        = int(time.time())
        if now - last_daily < 86400:
            remaining = 86400 - (now - last_daily)
            h, m      = remaining // 3600, (remaining % 3600) // 60
            embed = discord.Embed(
                title="⏳  Daily not ready",
                description=f"Come back in **{h}h {m}m** for your next reward.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        reward = random.randint(300, 700)
        self.add_chips(interaction.user.id, reward)
        self.cursor.execute(
            "UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id)
        )
        self.conn.commit()
        total = self.get_chips(interaction.user.id)
        embed = discord.Embed(title="💰  Daily reward claimed!", color=discord.Color.green())
        embed.add_field(name=f"{CHIP_EMOJI}  Reward",  value=f"**+{reward}**", inline=True)
        embed.add_field(name="💼  New balance",         value=f"**{total}**",   inline=True)
        embed.set_footer(text=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="chips", description="Check your chip balance")
    async def poker_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        embed = discord.Embed(title=f"{CHIP_EMOJI}  Chip Balance", color=discord.Color.gold())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**{chips:,}** chips"
        embed.set_footer(text="Use /daily to claim free chips every 24h")
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="create", description="Create a poker table")
    @app_commands.describe(table="Choose which table to open")
    @app_commands.choices(
        table=[
            app_commands.Choice(name="Dragon's Vault (10,000 buy-in, 5,000 max raise)", value="high_rollers"),
            app_commands.Choice(name="Firefly Den (1,000 buy-in, 500 max raise)", value="low_stakes"),
        ]
    )
    async def poker_create(
        self,
        interaction: discord.Interaction,
        table: app_commands.Choice[str],
    ):
        channel_id = interaction.channel.id
        if channel_id in self.poker_games:
            await interaction.response.send_message("A game is already active here.", ephemeral=True)
            return
        preset = TABLE_PRESETS[table.value]
        self.poker_games[channel_id] = {
            "host":              interaction.user.id,
            "table_key":         table.value,
            "table_name":        preset["name"],
            "buy_in":            preset["buy_in"],
            "raise_cap":         preset["raise_cap"],
            "players":           {},
            "deck":              [],
            "community":         [],
            "visible_community": [],
            "pot":               0,
            "phase":             "waiting",
            "current_bet":       0,
            "player_order":      [],
            "turn_index":        0,
        }
        embed = discord.Embed(
            title=f"{SPADE_EMOJI} {HEART_EMOJI}  {preset['name']}  {DIAM_EMOJI} {CLUB_EMOJI}",
            description=(
                f"Buy-in: **{preset['buy_in']}** {CHIP_EMOJI}\n"
                f"Max raise per turn: **{preset['raise_cap']}** {CHIP_EMOJI}\n\n"
                "Use `/poker join` to take a seat.\n"
                "Host uses `/poker start` when everyone is ready."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Hosted by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="join", description="Join the current poker table")
    async def poker_join(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game or game["phase"] != "waiting":
            await interaction.response.send_message("No joinable table here.", ephemeral=True)
            return
        if interaction.user.id in game["players"]:
            await interaction.response.send_message("You're already seated.", ephemeral=True)
            return
        buy_in = game["buy_in"]
        if not self.remove_chips(interaction.user.id, buy_in):
            await interaction.response.send_message(
                f"Not enough chips — you need **{buy_in}**.", ephemeral=True
            )
            return
        game["players"][interaction.user.id] = {
            "cards":         [],
            "folded":        False,
            "bet":           0,
            "acted":         False,
            "total_chip_in": buy_in,  # buy-in counts toward side-pot contributions
            "all_in":        False,
        }
        game["pot"] += buy_in
        embed = discord.Embed(
            description=f"✅  {interaction.user.mention} joined the table!  {CHIP_EMOJI} Pot: **{game['pot']}**",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="start", description="Start the game (host only)")
    async def poker_start(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("No table here.", ephemeral=True)
            return
        if interaction.user.id != game["host"]:
            await interaction.response.send_message("Only the host can start.", ephemeral=True)
            return
        if len(game["players"]) < 2:
            await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
            return

        deck              = build_deck()
        game["deck"]      = deck
        game["community"] = [deck.pop() for _ in range(5)]
        game["visible_community"] = []
        game["phase"]       = "preflop"
        game["current_bet"] = 0

        await interaction.response.defer()

        buy_in = game["buy_in"]
        for user_id, p in game["players"].items():
            p.update({
                "cards":         [deck.pop(), deck.pop()],
                "folded":        False,
                "bet":           0,
                "acted":         False,
                "total_chip_in": buy_in,  # reset to just the buy-in; bets add on top
                "all_in":        False,
            })
            try:
                member = await interaction.guild.fetch_member(user_id)
                await member.send(
                    f"🃏  Your hole cards:\n{format_cards(p['cards'])}\n"
                    f"*(Keep these secret!)*"
                )
            except Exception:
                pass

        game["player_order"] = list(game["players"].keys())
        game["turn_index"]   = 0
        current_uid          = game["player_order"][0]

        view  = PokerBetView(interaction.channel.id, game, self)
        embed = build_game_embed(game)
        await interaction.followup.send(f"<@{current_uid}>", embed=embed, view=view)

    @poker_group.command(name="setchips", description="Add or remove chips (admin)")
    @app_commands.check(is_owner)
    async def poker_setchips(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        self.ensure_chips(user.id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user.id)
        )
        self.conn.commit()
        total = self.get_chips(user.id)
        embed = discord.Embed(
            title=f"{CHIP_EMOJI}  Chips updated",
            color=discord.Color.green() if amount >= 0 else discord.Color.red(),
        )
        embed.add_field(name="Player",      value=user.mention,      inline=True)
        embed.add_field(name="Change",      value=f"**{amount:+}**", inline=True)
        embed.add_field(name="New balance", value=f"**{total:,}**",  inline=True)
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="end", description="Force-end the current game (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def poker_end(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.poker_games:
            await interaction.response.send_message("No active game here.", ephemeral=True)
            return
        del self.poker_games[interaction.channel.id]
        embed = discord.Embed(
            title="🛑  Game ended",
            description="The poker game has been force-ended by an admin.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PokerCog(bot))
