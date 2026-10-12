from django import template

register = template.Library()

class OjppLinkNode(template.Node):
    def __init__(self, obj, text=None):
        self.obj = template.Variable(obj)
        self.attr_name = template.Variable(text) if text else None

    def render(self, context):
        obj = self.obj.resolve(context)

        # TODO: XSS protection
        text = self.attr_name.resolve(context) if self.attr_name else str(obj)

        if getattr(obj, 'active', True):
            return f'<a href="{obj.get_absolute_url()}">{text}</a>'
        return f'<a href="{obj.get_absolute_url()}" class="deleted" title="DELETED">{text}</a>'

@register.tag
def ojpp_link(parser, token):
    """Return a link to the given object (get_absolute_url).
    If the model is soft-deletable and the object is inactive, a "deleted" class is added.
    Usage: {% ojpp_link obj [attr_name] %}
    Example: {% ojpp_link user %} or {% ojpp_link user user.username %}
    """
    bits: list = token.split_contents()
    if len(bits) not in (2, 3):
        raise template.TemplateSyntaxError(f'{bits[0]} tag requires one or two arguments')
    return OjppLinkNode(*bits[1:])