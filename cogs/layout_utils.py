import discord
from typing import Union, List, Optional

class LayoutView(discord.ui.LayoutView):
    """A standard LayoutView that handles basic timeout and item clearing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

def convert_embed_to_container(embed: discord.Embed) -> discord.ui.Container:
    """Converts a legacy discord.Embed into a ComponentsV2 Container."""
    container = discord.ui.Container(accent_color=embed.color)
    
    if embed.title:
        container.add_item(discord.ui.TextDisplay(f"## {embed.title}"))
        
    if embed.description:
        container.add_item(discord.ui.TextDisplay(embed.description))
        
    for field in embed.fields:
        # We use a Section for each field to maintain some separation
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**{field.name}**\n{field.value}")))
        
    if embed.image:
        container.add_item(discord.ui.MediaGallery().add_item(media=embed.image.url))
        
    if embed.thumbnail:
        # Thumbnails are usually small icons, we can add them to a Section or as a small Media item
        # But per docs, Thumbnail is a Section accessory.
        # Let's try to attach it to the first TextDisplay if it exists, or a new section.
        thumbnail = discord.ui.Thumbnail(media=embed.thumbnail.url)
        if container.children and isinstance(container.children[0], discord.ui.TextDisplay):
             # Section can wrap children and have an accessory
             first_item = container.children.pop(0)
             container.insert_item_at(0, discord.ui.Section(first_item, accessory=thumbnail))
        else:
             container.add_item(discord.ui.Section(accessory=thumbnail))

    if embed.footer:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(embed.footer.text))
        
    return container

def send_layout(interaction_or_ctx, container: discord.ui.Container, view: Optional[discord.ui.View] = None, **kwargs):
    """Utility to send a LayoutView with the given container and optional additional items."""
    layout_view = discord.ui.LayoutView()
    layout_view.add_item(container)
    if view:
        for item in view.children:
            layout_view.add_item(item)
            
    # For prefix commands (ctx)
    if hasattr(interaction_or_ctx, "send"):
        return interaction_or_ctx.send(view=layout_view, **kwargs)
    # For interactions
    elif hasattr(interaction_or_ctx, "response"):
        if interaction_or_ctx.response.is_done():
            return interaction_or_ctx.followup.send(view=layout_view, **kwargs)
        return interaction_or_ctx.response.send_message(view=layout_view, **kwargs)
    return None
