from django import template
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import get_language_info
from webpack_loader import utils


register = template.Library()


@register.simple_tag
def render_bundle_css(bundle_name, config='DEFAULT', attrs=''):
    """
    A tag to conditionally load css depending on whether the page is being rendered for
    an LTR or RTL language. Using webpack-rtl-plugin, we now have two css files for every
    bundle. One that just ends in .css for LTR, and the other that ends in .rtl.css for RTL.
    This will conditionally load the correct one depending on the current language setting.
    """
    bidi = get_language_info(get_language())['bidi']
    files = utils.get_files(bundle_name, extension='css', config=config)
    if bidi:
        files = [x for x in files if x['name'].endswith('rtl.css')]
    else:
        files = [x for x in files if not x['name'].endswith('rtl.css')]
    tags = []
    for chunk in files:
        tags.append((
            '<link type="text/css" href="{0}" rel="stylesheet" {1}/>'
        ).format(chunk['url'], attrs))
    return mark_safe('\n'.join(tags))
