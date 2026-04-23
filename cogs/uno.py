import random
from enum import Enum
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


COLOR_HEX = {
    "RED": 0xE74C3C,
    "YELLOW": 0xF1C40F,
    "GREEN": 0x2ECC71,
    "BLUE": 0x3498DB,
    "WILD": 0x9B59B6,
}

COLOR_SYMBOLS = {
    "RED": "🟥",
    "YELLOW": "🟨",
    "GREEN": "🟩",
    "BLUE": "🟦",
    "WILD": "🌈",
}

VALUE_LABELS = {
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
    "SKIP": "Skip",
    "REVERSE": "Reverse",
    "DRAW2": "+2",
    "WILD": "Wild",
    "WILD4": "+4",
}


class CardColor(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    BLUE = "BLUE"
    WILD = "WILD"


class CardValue(str, Enum):
    ZERO = "0"
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    SKIP = "SKIP"
    REVERSE = "REVERSE"
    DRAW2 = "DRAW2"
    WILD = "WILD"
    WILD4 = "WILD4"


class GameMode(str, Enum):
    CLASSIC = "classic"
    NO_MERCY = "no_mercy"


NO_MERCY_RULES = {
    "stackable_draws": True,
    "wild4_on_draw2": True,
    "stackable_skips": True,
}


class Card:
    def __init__(self, color: CardColor, value: CardValue):
        self.color = color
        self.value = value
        self.chosen_color: Optional[CardColor] = None

    @property
    def effective_color(self) -> CardColor:
        if self.color == CardColor.WILD and self.chosen_color:
            return self.chosen_color
        return self.color

    @property
    def is_wild(self) -> bool:
        return self.color == CardColor.WILD

    @property
    def emoji(self) -> str:
        if self.color == CardColor.WILD:
            return f"{COLOR_SYMBOLS['WILD']} {VALUE_LABELS[self.value.value]}"
        return f"{COLOR_SYMBOLS[self.color.value]} {VALUE_LABELS[self.value.value]}"

    @property
    def point_value(self) -> int:
        if self.value in (CardValue.WILD, CardValue.WILD4):
            return 50
        if self.value in (CardValue.SKIP, CardValue.REVERSE, CardValue.DRAW2):
            return 20
        return int(self.value.value)


class Deck:
    def __init__(self):
        self.cards: list[Card] = []
        self._build()
        self.shuffle()

    def _build(self):
        self.cards.clear()
        colors = [CardColor.RED, CardColor.YELLOW, CardColor.GREEN, CardColor.BLUE]
        for color in colors:
            self.cards.append(Card(color, CardValue.ZERO))
            for value in [
                CardValue.ONE,
                CardValue.TWO,
                CardValue.THREE,
                CardValue.FOUR,
                CardValue.FIVE,
                CardValue.SIX,
                CardValue.SEVEN,
                CardValue.EIGHT,
                CardValue.NINE,
                CardValue.SKIP,
                CardValue.REVERSE,
                CardValue.DRAW2,
            ]:
                self.cards.append(Card(color, value))
                self.cards.append(Card(color, value))
        for _ in range(4):
            self.cards.append(Card(CardColor.WILD, CardValue.WILD))
            self.cards.append(Card(CardColor.WILD, CardValue.WILD4))

    def shuffle(self):
        random.shuffle(self.cards)

    def draw(self) -> Optional[Card]:
        return self.cards.pop() if self.cards else None

    def replenish(self, discard_pile: list[Card]):
        if len(discard_pile) <= 1:
            return
        top = discard_pile[-1]
        refill = discard_pile[:-1]
        for card in refill:
            card.chosen_color = None
        self.cards = refill
        self.shuffle()
        discard_pile.clear()
        discard_pile.append(top)

    def __len__(self) -> int:
        return len(self.cards)


class Player:
    def __init__(self, member: discord.Member):
        self.member = member
        self.hand: list[Card] = []
        self.called_uno = False

    @property
    def id(self) -> int:
        return self.member.id

    @property
    def display_name(self) -> str:
        return self.member.display_name

    @property
    def card_count(self) -> int:
        return len(self.hand)

    def add_card(self, card: Card):
        self.hand.append(card)
        self.called_uno = False

    def remove_card(self, index: int) -> Card:
        return self.hand.pop(index)

    def points(self) -> int:
        return sum(card.point_value for card in self.hand)


def is_valid_play(card: Card, top_card: Card) -> bool:
    if card.is_wild:
        return True
    return card.color == top_card.effective_color or card.value == top_card.value


class UnoGame:
    def __init__(self, channel_id: int, host_id: int, mode: GameMode):
        self.channel_id = channel_id
        self.host_id = host_id
        self.mode = mode
        self.players: list[Player] = []
        self.deck = Deck()
        self.discard_pile: list[Card] = []
        self.turn_index = 0
        self.direction = 1
        self.started = False
        self.pending_draw = 0
        self.skip_stack = 0
        self.winner: Optional[Player] = None

    def add_player(self, member: discord.Member) -> Optional[str]:
        if self.started:
            return "The game has already started."
        if len(self.players) >= 10:
            return "Maximum 10 players reached."
        if any(player.id == member.id for player in self.players):
            return "You have already joined."
        self.players.append(Player(member))
        return None

    def start(self) -> Optional[str]:
        if len(self.players) < 2:
            return "Need at least 2 players to start."
        self.started = True
        random.shuffle(self.players)
        for _ in range(7):
            for player in self.players:
                card = self.deck.draw()
                if card:
                    player.add_card(card)
        while True:
            first = self.deck.draw()
            if first and not first.is_wild:
                self.discard_pile.append(first)
                break
            if first:
                self.deck.cards.insert(0, first)
        self._apply_start_card_effect()
        return None

    def _apply_start_card_effect(self):
        top = self.top_card
        if top.value == CardValue.SKIP:
            self.advance_turn()
        elif top.value == CardValue.REVERSE:
            self.direction = -1
            if len(self.players) == 2:
                self.advance_turn()
        elif top.value == CardValue.DRAW2 and self.mode == GameMode.CLASSIC:
            self.pending_draw += 2
            self._force_draw_if_needed()
            self.advance_turn()

    @property
    def current_player(self) -> Player:
        return self.players[self.turn_index]

    @property
    def top_card(self) -> Card:
        return self.discard_pile[-1]

    def advance_turn(self, steps: int = 1):
        self.turn_index = (self.turn_index + self.direction * steps) % len(self.players)

    def next_player_index(self, steps: int = 1) -> int:
        return (self.turn_index + self.direction * steps) % len(self.players)

    def _can_stack(self, card: Card) -> bool:
        if not NO_MERCY_RULES["stackable_draws"]:
            return False
        return card.value in (CardValue.DRAW2, CardValue.WILD4)

    def play_card(
        self,
        player: Player,
        card_index: int,
        chosen_color: Optional[CardColor] = None,
    ) -> tuple[bool, str]:
        if player.id != self.current_player.id:
            return False, "It's not your turn."
        if card_index < 0 or card_index >= len(player.hand):
            return False, "Invalid card index."

        card = player.hand[card_index]
        top = self.top_card

        if self.mode == GameMode.NO_MERCY and self.pending_draw > 0:
            if not self._can_stack(card):
                return False, f"You must stack a draw card or draw {self.pending_draw} cards."
        elif not is_valid_play(card, top):
            return False, "That card cannot be played here."

        if card.is_wild:
            if chosen_color is None:
                return False, "Choose a color for the wild card."
            card.chosen_color = chosen_color

        player.remove_card(card_index)
        self.discard_pile.append(card)
        player.called_uno = False
        return True, "OK"

    def apply_card_effect(self) -> dict:
        card = self.top_card
        result = {"skip": False, "reverse": False, "draw": 0, "next_draws": 0}

        if card.value == CardValue.SKIP:
            if self.mode == GameMode.NO_MERCY and NO_MERCY_RULES["stackable_skips"]:
                self.skip_stack += 1
            else:
                result["skip"] = True
                self.advance_turn()
        elif card.value == CardValue.REVERSE:
            self.direction *= -1
            result["reverse"] = True
            if len(self.players) == 2:
                result["skip"] = True
                self.advance_turn()
        elif card.value == CardValue.DRAW2:
            self.pending_draw += 2
            if self.mode == GameMode.CLASSIC:
                self._force_draw_if_needed()
                result["draw"] = 2
                result["skip"] = True
                self.advance_turn()
            else:
                result["next_draws"] = self.pending_draw
        elif card.value == CardValue.WILD4:
            self.pending_draw += 4
            if self.mode == GameMode.CLASSIC:
                self._force_draw_if_needed()
                result["draw"] = 4
                result["skip"] = True
                self.advance_turn()
            else:
                result["next_draws"] = self.pending_draw

        return result

    def _force_draw_if_needed(self):
        if self.pending_draw <= 0:
            return
        target = self.players[self.next_player_index()]
        self._give_cards(target, self.pending_draw)
        self.pending_draw = 0

    def _give_cards(self, player: Player, count: int):
        for _ in range(count):
            if not self.deck.cards:
                self.deck.replenish(self.discard_pile)
            card = self.deck.draw()
            if card:
                player.add_card(card)

    def draw_card(self, player: Player) -> tuple[bool, str, Optional[Card]]:
        if player.id != self.current_player.id:
            return False, "It's not your turn.", None

        if self.mode == GameMode.NO_MERCY and self.pending_draw > 0:
            count = self.pending_draw
            self._give_cards(player, count)
            self.pending_draw = 0
            self.advance_turn()
            if self.skip_stack > 0:
                self.advance_turn(self.skip_stack)
                self.skip_stack = 0
            return True, f"Drew {count} cards (stacked penalty).", None

        if not self.deck.cards:
            self.deck.replenish(self.discard_pile)
        card = self.deck.draw()
        if card is None:
            return False, "The deck is empty and cannot be replenished.", None
        player.add_card(card)
        return True, "Drew a card.", card

    def resolve_skip_stack(self):
        if self.mode == GameMode.NO_MERCY and self.skip_stack > 0:
            self.advance_turn(self.skip_stack)
            self.skip_stack = 0

    def check_winner(self) -> Optional[Player]:
        for player in self.players:
            if not player.hand:
                self.winner = player
                return player
        return None

    def call_uno(self, player: Player) -> tuple[bool, str]:
        if len(player.hand) != 1:
            return False, "You can only call UNO when you have exactly 1 card."
        player.called_uno = True
        return True, f"**{player.display_name}** called UNO."

    def catch_uno(self, caller: Player, target: Player) -> tuple[bool, str]:
        if caller.id == target.id:
            return False, "You can't catch yourself."
        if len(target.hand) == 1 and not target.called_uno:
            self._give_cards(target, 2)
            return True, f"**{target.display_name}** forgot to call UNO and draws 2 cards."
        return False, f"**{target.display_name}** is safe."

    def score_summary(self) -> list[tuple[str, int]]:
        return sorted(((player.display_name, player.points()) for player in self.players), key=lambda item: item[1])


def make_game_embed(game: UnoGame, extra_text: str = "") -> discord.Embed:
    top = game.top_card
    color_hex = COLOR_HEX.get(top.effective_color.value, 0x95A5A6)
    mode_label = "Classic UNO" if game.mode == GameMode.CLASSIC else "UNO No Mercy"
    embed = discord.Embed(title=mode_label, color=color_hex)

    top_display = top.emoji
    if top.is_wild and top.chosen_color:
        top_display += f" ({top.chosen_color.value.title()})"
    embed.add_field(name="Top Card", value=top_display, inline=True)
    embed.add_field(name="Draw Pile", value=str(len(game.deck)), inline=True)

    if game.pending_draw > 0:
        embed.add_field(name="Stacked Draw", value=f"+{game.pending_draw} pending", inline=True)

    turn_lines = []
    for index, player in enumerate(game.players):
        marker = "-> " if index == game.turn_index else "   "
        uno_flag = " | UNO" if player.called_uno else ""
        turn_lines.append(f"{marker}{player.display_name} - {player.card_count} card(s){uno_flag}")
    embed.add_field(name="Players", value="\n".join(turn_lines), inline=False)

    if extra_text:
        embed.add_field(name="Status", value=extra_text, inline=False)

    embed.set_footer(text="Use the buttons below or /uno hand to see your cards.")
    return embed


def make_hand_embed(player: Player, game: UnoGame, page: int = 0) -> discord.Embed:
    top = game.top_card
    start = page * 25
    end = start + 25
    cards = player.hand[start:end]

    embed = discord.Embed(
        title="Your UNO Hand",
        description=f"Top card: {top.emoji}",
        color=discord.Color.dark_grey(),
    )

    if not player.hand:
        embed.add_field(name="Cards", value="(empty)", inline=False)
        return embed

    lines = []
    for absolute_index, card in enumerate(cards, start=start + 1):
        playable = is_valid_play(card, top)
        if game.mode == GameMode.NO_MERCY and game.pending_draw > 0:
            playable = game._can_stack(card)
        mark = "✅" if playable else "❌"
        lines.append(f"`{absolute_index}.` {card.emoji} {mark}")

    embed.add_field(name="Cards", value="\n".join(lines), inline=False)
    total_pages = max(1, (len(player.hand) + 24) // 25)
    embed.set_footer(text=f"Page {page + 1}/{total_pages} | ✅ playable | ❌ blocked")
    return embed


class ColorChooserView(discord.ui.View):
    def __init__(self, cog: "UnoCog", game: UnoGame, player: Player, card_index: int, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.game = game
        self.player = player
        self.card_index = card_index
        self.channel = channel

    async def _pick(self, interaction: discord.Interaction, color: CardColor):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your action.", ephemeral=True)
            return

        success, msg = self.game.play_card(self.player, self.card_index, chosen_color=color)
        if not success:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        effect = self.game.apply_card_effect()
        winner = self.game.check_winner()
        await interaction.response.defer()
        self.stop()

        extra = f"**{self.player.display_name}** played {self.game.top_card.emoji} and chose **{color.value.title()}**."
        if effect.get("next_draws", 0) > 0:
            extra += f"\nStack total: +{effect['next_draws']}."

        if winner:
            await self.cog.end_game(self.channel, self.game, winner, extra)
            return

        if self.game.mode == GameMode.CLASSIC:
            if not effect.get("skip"):
                self.game.advance_turn()
        elif not effect.get("skip"):
            self.game.advance_turn()

        await self.cog.refresh_game_state(self.channel, self.game, extra)

    @discord.ui.button(label="Red", style=discord.ButtonStyle.danger)
    async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, CardColor.RED)

    @discord.ui.button(label="Yellow", style=discord.ButtonStyle.secondary)
    async def yellow(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, CardColor.YELLOW)

    @discord.ui.button(label="Green", style=discord.ButtonStyle.success)
    async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, CardColor.GREEN)

    @discord.ui.button(label="Blue", style=discord.ButtonStyle.primary)
    async def blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, CardColor.BLUE)

    async def on_timeout(self):
        color = random.choice([CardColor.RED, CardColor.YELLOW, CardColor.GREEN, CardColor.BLUE])
        success, _ = self.game.play_card(self.player, self.card_index, chosen_color=color)
        if not success:
            return
        effect = self.game.apply_card_effect()
        winner = self.game.check_winner()
        extra = f"Auto-picked **{color.value.title()}** for **{self.player.display_name}**."
        if effect.get("next_draws", 0) > 0:
            extra += f"\nStack total: +{effect['next_draws']}."
        if winner:
            await self.cog.end_game(self.channel, self.game, winner, extra)
            return
        if self.game.mode == GameMode.CLASSIC:
            if not effect.get("skip"):
                self.game.advance_turn()
        elif not effect.get("skip"):
            self.game.advance_turn()
        await self.cog.refresh_game_state(self.channel, self.game, extra)


class CardSelect(discord.ui.Select):
    def __init__(self, view: "CardPickerView"):
        self.card_view = view
        game = view.game
        player = view.player
        top = game.top_card

        start = view.page * 25
        end = min(start + 25, len(player.hand))
        options = []
        for index in range(start, end):
            card = player.hand[index]
            playable = is_valid_play(card, top)
            if game.mode == GameMode.NO_MERCY and game.pending_draw > 0:
                playable = game._can_stack(card)
            prefix = "✅" if playable else "❌"
            options.append(
                discord.SelectOption(
                    label=f"{index + 1}. {VALUE_LABELS[card.value.value]}",
                    description=f"{card.color.value.title()}",
                    value=str(index),
                    emoji=COLOR_SYMBOLS[card.effective_color.value if card.color == CardColor.WILD and card.chosen_color else card.color.value],
                )
            )
        super().__init__(
            placeholder="Choose a card number to play",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.card_view.player.id:
            await interaction.response.send_message("Not your hand.", ephemeral=True)
            return

        card_index = int(self.values[0])
        card = self.card_view.player.hand[card_index]
        game = self.card_view.game

        playable = is_valid_play(card, game.top_card)
        if game.mode == GameMode.NO_MERCY and game.pending_draw > 0:
            playable = game._can_stack(card)
        if not playable:
            await interaction.response.send_message("That card isn't playable right now.", ephemeral=True)
            return

        if card.is_wild:
            await interaction.response.send_message(
                "Choose a color for your wild card.",
                view=ColorChooserView(self.card_view.cog, game, self.card_view.player, card_index, self.card_view.channel),
                ephemeral=True,
            )
            self.card_view.stop()
            return

        success, msg = game.play_card(self.card_view.player, card_index)
        if not success:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        effect = game.apply_card_effect()
        winner = game.check_winner()
        await interaction.response.defer()
        self.card_view.stop()

        extra = f"**{self.card_view.player.display_name}** played {game.top_card.emoji}."
        if effect.get("reverse"):
            extra += "\nDirection reversed."
        if effect.get("next_draws", 0) > 0:
            extra += f"\nStack total: +{effect['next_draws']}."

        if winner:
            await self.card_view.cog.end_game(self.card_view.channel, game, winner, extra)
            return

        if game.mode == GameMode.CLASSIC:
            if not effect.get("skip"):
                game.advance_turn()
        elif not effect.get("skip") and game.pending_draw == 0:
            game.advance_turn()

        await self.card_view.cog.refresh_game_state(self.card_view.channel, game, extra)


class CardPickerView(discord.ui.View):
    def __init__(self, cog: "UnoCog", game: UnoGame, player: Player, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.game = game
        self.player = player
        self.channel = channel
        self.page = 0
        self.expected_turn_index = game.turn_index
        self.expected_discard_count = len(game.discard_pile)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        self.add_item(CardSelect(self))
        total_pages = max(1, (len(self.player.hand) + 24) // 25)
        self.previous_page.disabled = self.page == 0
        self.next_page.disabled = self.page >= total_pages - 1
        self.add_item(self.previous_page)
        self.add_item(self.next_page)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Not your hand.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self._rebuild()
        await interaction.response.edit_message(embed=make_hand_embed(self.player, self.game, self.page), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Not your hand.", ephemeral=True)
            return
        total_pages = max(1, (len(self.player.hand) + 24) // 25)
        self.page = min(total_pages - 1, self.page + 1)
        self._rebuild()
        await interaction.response.edit_message(embed=make_hand_embed(self.player, self.game, self.page), view=self)

    async def on_timeout(self):
        if self.game.current_player.id != self.player.id:
            return
        if self.game.turn_index != self.expected_turn_index:
            return
        if len(self.game.discard_pile) != self.expected_discard_count:
            return
        self.game.advance_turn()
        await self.cog.refresh_game_state(self.channel, self.game, f"**{self.player.display_name}** ran out of time.")


class GameView(discord.ui.View):
    def __init__(self, cog: "UnoCog", game: UnoGame):
        super().__init__(timeout=300)
        self.cog = cog
        self.game = game

    def _get_player(self, interaction: discord.Interaction) -> Optional[Player]:
        return next((player for player in self.game.players if player.id == interaction.user.id), None)

    @discord.ui.button(label="Play Card", style=discord.ButtonStyle.primary)
    async def play_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.game.started:
            await interaction.response.send_message("The game hasn't started yet.", ephemeral=True)
            return
        player = self._get_player(interaction)
        if not player:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        if player.id != self.game.current_player.id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        view = CardPickerView(self.cog, self.game, player, interaction.channel)
        await interaction.response.send_message(
            embed=make_hand_embed(player, self.game, 0),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Draw Card", style=discord.ButtonStyle.secondary)
    async def draw_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player(interaction)
        if not player:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        if player.id != self.game.current_player.id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return

        success, msg, drawn = self.game.draw_card(player)
        if not success:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.send_message(f"{msg}", ephemeral=True)
        extra = f"**{player.display_name}** drew a card."
        if "stacked penalty" in msg:
            extra = f"**{player.display_name}** absorbed the stack and drew cards."
        else:
            self.game.advance_turn()
            if self.game.mode == GameMode.CLASSIC and drawn and is_valid_play(drawn, self.game.top_card):
                extra += " The drawn card is playable and was added to their hand."
        await self.cog.refresh_game_state(interaction.channel, self.game, extra)

    @discord.ui.button(label="Call UNO", style=discord.ButtonStyle.danger)
    async def call_uno(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player(interaction)
        if not player:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        success, msg = self.game.call_uno(player)
        await interaction.response.send_message(msg, ephemeral=not success)
        if success:
            await self.cog.refresh_game_state(interaction.channel, self.game, msg)

    @discord.ui.button(label="Show Hand", style=discord.ButtonStyle.success)
    async def show_hand(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player(interaction)
        if not player:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        await interaction.response.send_message(embed=make_hand_embed(player, self.game, 0), ephemeral=True)


class LobbyView(discord.ui.View):
    def __init__(self, cog: "UnoCog", game: UnoGame, channel: discord.TextChannel):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self.channel = channel

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        err = self.game.add_player(interaction.user)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        player_list = "\n".join(f"- {player.display_name}" for player in self.game.players)
        await interaction.response.send_message(f"Joined the lobby.\n\nPlayers:\n{player_list}")

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
            return
        err = self.game.start()
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        self.stop()
        await interaction.response.defer()
        mode_label = "Classic UNO" if self.game.mode == GameMode.CLASSIC else "UNO No Mercy"
        await self.channel.send(f"**{mode_label}** has begun.")
        await self.cog.refresh_game_state(self.channel, self.game, "Game started.")

    async def on_timeout(self):
        if not self.game.started:
            self.cog.active_games.pop(self.game.channel_id, None)
            await self.channel.send("UNO lobby timed out.")


class UnoCog(commands.Cog, name="UNO"):
    uno_group = app_commands.Group(name="uno", description="Play UNO in the current channel")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, UnoGame] = {}
        self.last_game_messages: dict[int, discord.Message] = {}

    async def refresh_game_state(self, channel: discord.TextChannel, game: UnoGame, extra: str = ""):
        old_msg = self.last_game_messages.pop(channel.id, None)
        if old_msg:
            try:
                await old_msg.delete()
            except discord.HTTPException:
                pass

        game.resolve_skip_stack()
        embed = make_game_embed(game, extra)
        view = GameView(self, game)
        msg = await channel.send(embed=embed, view=view)
        self.last_game_messages[channel.id] = msg

        current = game.current_player
        try:
            await current.member.send(
                f"It's your turn in #{channel.name}.",
                embed=make_hand_embed(current, game, 0),
            )
        except discord.Forbidden:
            pass

    async def end_game(self, channel: discord.TextChannel, game: UnoGame, winner: Player, extra: str = ""):
        self.active_games.pop(channel.id, None)
        old_msg = self.last_game_messages.pop(channel.id, None)
        if old_msg:
            try:
                await old_msg.delete()
            except discord.HTTPException:
                pass

        scores = game.score_summary()
        score_text = "\n".join(f"{name} - **{points}** pts" for name, points in scores)
        embed = discord.Embed(
            title=f"{winner.display_name} wins UNO.",
            description=f"{extra}\n\nFinal scores:\n{score_text}",
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Thanks for playing.")
        await channel.send(embed=embed)

    async def _show_hand(self, target, author: discord.abc.User):
        channel = target.channel
        game = self.active_games.get(channel.id)
        if not game or not game.started:
            message = "No active UNO game."
            if isinstance(target, commands.Context):
                await target.send(message, delete_after=5)
            else:
                await target.response.send_message(message, ephemeral=True)
            return

        player = next((entry for entry in game.players if entry.id == author.id), None)
        if not player:
            message = "You're not in this game."
            if isinstance(target, commands.Context):
                await target.send(message, delete_after=5)
            else:
                await target.response.send_message(message, ephemeral=True)
            return

        embed = make_hand_embed(player, game, 0)
        if isinstance(target, commands.Context):
            try:
                await author.send(embed=embed)
                await target.message.delete()
            except (discord.Forbidden, discord.HTTPException):
                await target.send(embed=embed, delete_after=15)
        else:
            await target.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="uno")
    async def uno_prefix(self, ctx: commands.Context, mode: str = "classic"):
        if not isinstance(ctx.author, discord.Member):
            await ctx.send("This command only works in a server.")
            return
        if ctx.channel.id in self.active_games:
            await ctx.send("A UNO game is already running in this channel. Use `;unoend` first.")
            return

        normalized = mode.lower().replace(" ", "").replace("_", "").replace("-", "")
        if normalized in ("nomercy", "mercy", "hardcore", "nm"):
            game_mode = GameMode.NO_MERCY
        elif normalized in ("classic", "normal", "standard"):
            game_mode = GameMode.CLASSIC
        else:
            await ctx.send("Unknown mode. Use `;uno classic` or `;uno nomercy`.")
            return

        game = UnoGame(ctx.channel.id, ctx.author.id, game_mode)
        game.add_player(ctx.author)
        self.active_games[ctx.channel.id] = game

        mode_label = "Classic UNO" if game_mode == GameMode.CLASSIC else "UNO No Mercy"
        extra = ""
        if game_mode == GameMode.NO_MERCY:
            extra = (
                "\n\n**No Mercy Rules**\n"
                "- Draw cards stack.\n"
                "- Wild +4 can stack.\n"
                "- Skips stack.\n"
                "- If you can't stack, you draw the whole pile."
            )

        embed = discord.Embed(
            title=f"{mode_label} Lobby",
            description=(
                f"Host: **{ctx.author.display_name}**\n"
                "Press **Join Game** to join.\n"
                "Host presses **Start Game** when ready."
                f"{extra}"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=LobbyView(self, game, ctx.channel))

    @uno_group.command(name="start", description="Start a UNO lobby in this channel")
    @app_commands.describe(mode="Choose classic or nomercy")
    async def uno_start_slash(self, interaction: discord.Interaction, mode: str = "classic"):
        ctx = await commands.Context.from_interaction(interaction)
        await self.uno_prefix.callback(self, ctx, mode)

    @commands.command(name="unoend")
    async def uno_end_prefix(self, ctx: commands.Context):
        game = self.active_games.get(ctx.channel.id)
        if not game:
            await ctx.send("No active UNO game in this channel.")
            return
        is_admin = isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator
        is_host = ctx.author.id == game.host_id
        if not (is_admin or is_host):
            await ctx.send("Only the host or an admin can end the game.")
            return
        self.active_games.pop(ctx.channel.id, None)
        old_msg = self.last_game_messages.pop(ctx.channel.id, None)
        if old_msg:
            try:
                await old_msg.delete()
            except discord.HTTPException:
                pass
        await ctx.send(f"UNO game ended by **{ctx.author.display_name}**.")

    @uno_group.command(name="end", description="Force-end the current UNO game")
    async def uno_end_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.uno_end_prefix.callback(self, ctx)

    @commands.command(name="unohand")
    async def unohand_prefix(self, ctx: commands.Context):
        await self._show_hand(ctx, ctx.author)

    @uno_group.command(name="hand", description="Show your UNO hand")
    async def uno_hand_slash(self, interaction: discord.Interaction):
        await self._show_hand(interaction, interaction.user)

    @commands.command(name="unocatch")
    async def unocatch_prefix(self, ctx: commands.Context, member: discord.Member):
        game = self.active_games.get(ctx.channel.id)
        if not game or not game.started:
            await ctx.send("No active UNO game.", delete_after=5)
            return
        caller = next((player for player in game.players if player.id == ctx.author.id), None)
        target = next((player for player in game.players if player.id == member.id), None)
        if not caller:
            await ctx.send("You're not in this game.", delete_after=5)
            return
        if not target:
            await ctx.send("That player isn't in this game.", delete_after=5)
            return
        success, msg = game.catch_uno(caller, target)
        await ctx.send(msg)
        if success:
            await self.refresh_game_state(ctx.channel, game, msg)

    @uno_group.command(name="catch", description="Catch a player who forgot to call UNO")
    async def unocatch_slash(self, interaction: discord.Interaction, member: discord.Member):
        ctx = await commands.Context.from_interaction(interaction)
        await self.unocatch_prefix.callback(self, ctx, member)

    @commands.command(name="unostatus")
    async def unostatus_prefix(self, ctx: commands.Context):
        game = self.active_games.get(ctx.channel.id)
        if not game or not game.started:
            await ctx.send("No active UNO game.", delete_after=5)
            return
        await self.refresh_game_state(ctx.channel, game, "Game state refreshed.")

    @uno_group.command(name="status", description="Refresh the UNO game state")
    async def unostatus_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.unostatus_prefix.callback(self, ctx)

    @commands.command(name="unohelp")
    async def unohelp_prefix(self, ctx: commands.Context):
        embed = discord.Embed(title="UNO Commands", color=discord.Color.purple())
        commands_list = [
            ("`;uno [classic|nomercy]`", "Start a new UNO lobby"),
            ("`;unoend`", "End the current UNO game"),
            ("`;unohand`", "Show your current hand"),
            ("`;unocatch @player`", "Catch a player who forgot to call UNO"),
            ("`;unostatus`", "Refresh the public game embed"),
            ("`/uno start`", "Start a new UNO lobby"),
            ("`/uno hand`", "Show your hand"),
        ]
        for name, description in commands_list:
            embed.add_field(name=name, value=description, inline=False)
        embed.add_field(
            name="Buttons",
            value=(
                "**Play Card** - open your hand picker\n"
                "**Draw Card** - draw from the deck\n"
                "**Call UNO** - call UNO with 1 card left\n"
                "**Show Hand** - view your hand privately"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @uno_group.command(name="help", description="Show UNO help")
    async def unohelp_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.unohelp_prefix.callback(self, ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(UnoCog(bot))
