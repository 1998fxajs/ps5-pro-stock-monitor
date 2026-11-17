"""Extract one public post/product, never the surrounding site navigation."""
import re
from html import escape
from html.parser import HTMLParser

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
SKIP = {'script','style','noscript','nav','footer','aside','form'}
NOISE = re.compile(r'(?:^|[\s_-])(?:related|recommend\w*|sidebar|comments?|reply|advert\w*|banner|navigation|menu)(?:$|[\s_-])',re.I)
BODY = {'write_div','entry-content','post-content','article-body','articleBody','article_content','article-content','newsct_article','news_body_area','read_body','rd_body','view_content','writeContent','board-contents','xe_content','document_content','prdDetail','prdDesc','product-detail'}

class Node:
    def __init__(self,tag='',attrs=()): self.tag=tag; self.attrs=dict(attrs); self.children=[]
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child,Node): yield from child.walk()
    def text(self):
        return ' '.join(c.text() if isinstance(c,Node) else c for c in self.children)
    def html(self):
        label=self.attrs.get('class','')+' '+self.attrs.get('id','')
        if self.tag in SKIP or NOISE.search(label): return ''
        attrs=''.join(' '+k+'="'+escape(v or '',quote=True)+'"' for k,v in self.attrs.items())
        inner=''.join(c.html() if isinstance(c,Node) else escape(c) for c in self.children)
        return '<'+self.tag+attrs+'>'+inner+('' if self.tag in VOID else '</'+self.tag+'>')

class Document(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True); self.root=Node(); self.stack=[self.root];self.feed(html)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs);self.stack[-1].children.append(node)
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: del self.stack[i:];break
    def handle_data(self,data): self.stack[-1].children.append(data)

def extract(html,url=''):
    doc=Document(html);nodes=list(doc.root.walk()); candidates=[];metadata={}
    for node in nodes:
        a=node.attrs;tokens=set((a.get('class','')+' '+a.get('id','')).split())
        if node.tag=='meta':
            key=a.get('property',a.get('name','')).lower()
            if key in ('article:published_time','datepublished','date','pubdate','og:title'): metadata[key]=a.get('content','')
        if node.tag=='time' and a.get('datetime'):metadata.setdefault('datepublished',a['datetime'])
        if node.tag=='h1':metadata.setdefault('heading',node.text().strip())
        if 'write_div' in tokens:candidates.append((100,node))
        elif tokens & BODY or a.get('itemprop') in ('articleBody','description'):candidates.append((80,node))
        elif any(x.startswith('document_') for x in tokens):candidates.append((70,node))
        elif node.tag=='article':candidates.append((40,node))
        elif node.tag=='main' or a.get('role')=='main':candidates.append((20,node))
    if candidates:
        top=max(x[0] for x in candidates)
        selected=max((n for score,n in candidates if score==top),key=lambda n:len(n.text()))
        return selected.html(),metadata
    # Unit fixtures / RSS fragments are already scoped. A full unknown page
    # must not be treated as a successfully read post.
    if not re.search(r'<(?:html|body|head)\b',html,re.I):return html,metadata
    return '',metadata
