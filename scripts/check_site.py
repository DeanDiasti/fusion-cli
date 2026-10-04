"""Check local site navigation, crawlable metadata, and sitemap consistency."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'site'
BASE = 'https://deandiasti.github.io/fusion-cli/'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.metadata, self.canonicals = [], {}, []
        self.h1 = self.titles = 0
        self.structured = []
        self.in_json = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1': self.h1 += 1
        if tag == 'title': self.titles += 1
        if tag == 'meta': self.metadata[attrs.get('name', attrs.get('property'))] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical': self.canonicals.append(attrs['href'])
        if tag in ('a', 'link') and 'href' in attrs: self.links.append(attrs['href'])
        if tag in ('img', 'script') and 'src' in attrs: self.links.append(attrs['src'])
        if tag == 'script' and attrs.get('type') == 'application/ld+json': self.in_json = True

    def handle_endtag(self, tag):
        if tag == 'script': self.in_json = False

    def handle_data(self, data):
        if self.in_json: self.structured.append(json.loads(data))


def main():
    urls = set()
    for path in ROOT.rglob('*.html'):
        page = Page(); page.feed(path.read_text())
        relative = path.parent.relative_to(ROOT).as_posix()
        url = BASE + (relative + '/' if relative != '.' else '')
        assert page.canonicals == [url], str(path) + ': canonical mismatch'
        assert page.h1 == page.titles == 1, str(path) + ': expected one title and heading'
        assert page.metadata.get('description') and page.metadata.get('og:description'), str(path)
        assert page.metadata.get('robots') == 'index,follow', str(path)
        assert page.structured and page.structured[0]['url'] == url, str(path)
        for target in page.links:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path: continue
            dest = (path.parent / unquote(parsed.path)).resolve()
            assert dest.is_relative_to(ROOT.resolve()), target + ': outside site'
            if dest.is_dir(): dest /= 'index.html'
            assert dest.is_file(), str(path) + ': broken link ' + target
        urls.add(url)
    sitemap = ET.parse(ROOT / 'sitemap.xml')
    locations = {node.text for node in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')}
    assert urls == locations, 'Sitemap and page URLs differ'
    print('Site checks passed:', len(urls), 'pages with valid local links and search metadata.')


if __name__ == '__main__': main()
