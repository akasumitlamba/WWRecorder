"""Static-site navigation and published download safety contracts; browser actions live in tests/website."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import pytest

ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/'Supporting/Website/site' if (ROOT/'Supporting/Website/site').is_dir() else ROOT

class Page(HTMLParser):
    def __init__(self,source):
        super().__init__();self.links=[];self.ids=[];self.feed(source)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.append(attrs['id'])
        if tag=='a' and 'href' in attrs:self.links.append(attrs['href'])

@pytest.mark.parametrize('name',['index.html','download.html','privacy-policy.html','enterprise.html','install-help.html','legal.html','specs.html'])
def test_enterprise_is_reachable_without_script(name):
    page=Page((SITE/name).read_text())
    assert 'enterprise.html' in page.links
    assert len(page.ids)==len(set(page.ids)),name
    for link in page.links:
        parsed=urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path.endswith('.html'):continue
        target=SITE/parsed.path
        assert target.is_file(),link
        if parsed.fragment:assert parsed.fragment in Page(target.read_text()).ids,link

def test_enterprise_policy_names_match_runtime_allowlist():
    # Documented administrator restrictions must be implemented, not marketing promises.
    import sys
    sys.path.insert(0,str(ROOT/'app'))
    import enterprise_policy
    assert enterprise_policy.disabled('NotAPolicy') is False
    import ast
    parsed=ast.parse((ROOT/'app/enterprise_policy.py').read_text())
    allowed=next(n.comparators[0] for n in ast.walk(parsed) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Name) and n.left.id=='name')
    documented=(SITE/'enterprise.html').read_text()
    for name in ast.literal_eval(allowed):assert 'Disable'+name in documented
