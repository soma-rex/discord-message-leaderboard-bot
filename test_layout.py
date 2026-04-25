import discord
from discord.ui import LayoutView

class MyView(LayoutView):
    @discord.ui.button(label="Test")
    async def test_btn(self, interaction, button):
        pass

v = MyView()
print(v.children)
