"""Bounded, fixed-current UI and rich-text resource inspection.

This module reads preserved bytes only. It never executes HTML, navigates a
link, changes a layout, or upgrades a character's runtime acceptance.
"""
import hashlib
import json
import math
import copy
import re
import xml.etree.ElementTree as ET
import zlib

LIMIT = 4 * 1024 * 1024
MAX_NODES = 50_000
MAX_DEPTH = 128
SWF = "9418137820c007b52a11ad0d7955c102795d8dd903213670577bf3407ed709f7"
BASIS = {
    "FileReader": "80ac1d8396acc2e11981d55a17228281b2b09955c384932372d409eb9043ff10",
    "AssetPathCollectionBuilder": "dc1d5dbfe465762aa39873c006179f3532e8cfb8b991344b5f4e57d5db5bce2c",
    "ViewAssetCache": "1fe7fa78635098ef9a566827ed5fe843fb3886093b64aa4005b48198fefe6d53",
    "FollowingLogicAssetCache": "a559cd097c8da2e34f2feac96f61141e68dfc5a24027584802f3d37db98446a5",
    "RichTextLayoutParser": "da18d817ffd08bc86c5dfd9daad4cc883789c227e4b00785c588603b80b8ef09",
    "UiProviderImpl": "b9aa7c55fe572081472880a0324ff57e015ed6f3db751a66d133a7cc94a869fa",
    "UiImageFactroy": "1bce02e856fe96e732384837109a1c4eecd89041160767513b0e49270dabab3e",
    "UiText": "3978d58cf988ce804daa8653c4ace367881015848023c48c2db30963f0cb5cd3",
    "RichTextImageLoader": "35303b12e283077d17b3323d8cec3a8ce4748a93e53f437d119e152276c242c0",
    "RichTextLayoutImage": "54ebad491b7f7e0cac107b6e186b22f0cd9719a39369cbb2acf7428dd4ab775c",
    "RichTextLayoutButton": "956c49ad4795f9259da449107338da2f7e668e368d861d3ffca76b96106c5e48",
    "ButtonBackgroundDefaultConfigs": "ceaeb77e9abfbfeaa97cabb51cde588275a91ab30b0dd1be18347d494ac7cc84",
    "ButtonContentDefaultConfigs": "f95ccec6fe7baef96f7562c47548db326cca9576e2ab792f18f0125aa25ec61e",
    "RichTextLayoutParser.getLayoutData.body": "2625cc31ad9d8316e81ca033bc00b09b41f56c4c0074bf310e8b91899c8588c1",
    "boot.buttonPresets": "e7da4efa9d1e44495b949b86d0ff0f74781f869cfbecc0e8d1935fed9ed30848",
    "BoxButtonBackgroundFactory": "4a03c5f3b381724cf71c8e6932693ff50701ed1b5864b97069ed374d9ae6ad27",
    "DownBlurFactory": "1682d28349337949f8faa68f91bad0be1f250b3249311066d0227d74a17a219f",
    "ButtonDecorationFactory": "532310d28f05cd17ffec4cd84eda1f385aff3f311b0696c2df69db65ce560792",
}


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("UI素材路径必须是非空短字符串")
    if value.startswith("/") or any(c in value for c in "\\\x00\r\n\t:?#"):
        raise ValueError("UI素材路径不是本地逻辑路径")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("UI素材路径含空段或越界段")
    return value


def physical_path(logical, kind, intermediate=False):
    """Exact FileReader suffix, without selecting a guessed client read kind."""
    logical = _path(logical)
    suffixes = {"ui": (".ui.json", ".ui.amf3.deflate"), "html": (".html", ".html.deflate")}
    if kind not in suffixes:
        raise ValueError("只支持当前UI与rich-text格式")
    if any(logical.endswith(suffix) for suffix in suffixes[kind]):
        return logical
    return logical + suffixes[kind][0 if intermediate else 1]


def _inflate(raw):
    decoder = zlib.decompressobj(-15)
    decoded = decoder.decompress(raw, LIMIT + 1)
    if len(decoded) > LIMIT or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
        raise ValueError("UI解压超限、流截断或含尾随数据")
    return decoded


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("UI JSON包含重复字段")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("UI JSON非有限数字")))


def _amf(raw):
    from bridge import AMF3Reader

    class Reader(AMF3Reader):
        def __init__(self, data):
            super().__init__(data)
            self.depth = 0
            self.count = 0

        def budget(self):
            self.count += 1
            if self.count > MAX_NODES:
                raise ValueError("UI AMF节点/字段数量超限")

        def read_byte(self):
            if self.pos >= len(self.data):
                raise ValueError("UI AMF流截断")
            return super().read_byte()

        def ref(self, values, index):
            if index < 0 or index >= len(values):
                raise ValueError("UI AMF引用索引无效")
            return values[index]

        def read_string_body(self):
            self.budget()
            header = self.read_u29()
            if not header & 1:
                return self.ref(self.string_refs, header >> 1)
            size = header >> 1
            if size > len(self.data) - self.pos:
                raise ValueError("UI AMF字符串截断")
            value = self.data[self.pos:self.pos + size].decode("utf-8")
            self.pos += size
            if size:
                self.string_refs.append(value)
            return value

        def read_value(self):
            self.budget()
            self.depth += 1
            try:
                if self.depth > MAX_DEPTH:
                    raise ValueError("UI AMF嵌套超限")
                if self.pos >= len(self.data):
                    raise ValueError("UI AMF值截断")
                if self.data[self.pos] == 5 and len(self.data) - self.pos < 9:
                    raise ValueError("UI AMF浮点值截断")
                value = super().read_value()
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("UI AMF非有限数字")
                return value
            finally:
                self.depth -= 1

        def read_array(self):
            header = self.read_u29()
            if not header & 1:
                return self.ref(self.object_refs, header >> 1)
            count = header >> 1
            if count > MAX_NODES:
                raise ValueError("UI AMF数组声明数量超限")
            assoc = {}
            while True:
                key = self.read_string_body()
                if not key:
                    break
                if key in assoc:
                    raise ValueError("UI AMF数组关联字段重复")
                assoc[key] = self.read_value()
            dense = []
            value = dense if not assoc else {"$assoc": assoc, "$dense": dense}
            self.object_refs.append(value)
            for _ in range(count):
                dense.append(self.read_value())
            return value

        def read_object(self):
            header = self.read_u29()
            if not header & 1:
                return self.ref(self.object_refs, header >> 1)
            if not header & 2:
                name, sealed, external, dynamic = self.ref(self.trait_refs, header >> 2)
            else:
                external, dynamic = bool(header & 4), bool(header & 8)
                count = header >> 4
                if count > MAX_NODES:
                    raise ValueError("UI AMF对象声明字段数量超限")
                name = self.read_string_body()
                sealed = [self.read_string_body() for _ in range(count)]
                if len(set(sealed)) != len(sealed):
                    raise ValueError("UI AMF密封字段重复")
                self.trait_refs.append((name, sealed, external, dynamic))
            if external:
                raise ValueError("UI AMF externalizable类型尚不支持")
            result = {}
            if name:
                result["$class"] = name
            self.object_refs.append(result)
            for key in sealed:
                if key in result:
                    raise ValueError("UI AMF类型与字段冲突")
                result[key] = self.read_value()
            if dynamic:
                while True:
                    key = self.read_string_body()
                    if not key:
                        break
                    if key in result:
                        raise ValueError("UI AMF动态字段重复")
                    result[key] = self.read_value()
            return result

    reader = Reader(raw)
    result = reader.read_value()
    if reader.pos != len(raw):
        raise ValueError("UI AMF单值后有尾随字节")
    return result


def _pointer(base, key):
    return base + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _tree_budget(data):
    """Reject cycles and huge/deep decoded inputs without recursive inspection."""
    active = set()
    stack = [(data, 0, False)]
    nodes = 0
    while stack:
        value, depth, leave = stack.pop()
        if leave:
            active.remove(id(value))
            continue
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("UI解码树节点或嵌套超限")
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ValueError("UI解码树包含循环对象引用")
            active.add(id(value))
            stack.append((value, depth, True))
            children = list(value.values()) if isinstance(value, dict) else value
            stack.extend((child, depth + 1, False) for child in reversed(children))


class _Report:
    def __init__(self, logical, raw, kind, context, pointer):
        self.pointer = pointer
        self.kind = kind
        self.context = dict(context or {})
        self.source = {"logical": logical, "sha256": hashlib.sha256(raw).hexdigest(),
                       "format": kind, "bytes": len(raw)}
        self.result = {"references": [], "problems": [], "texts": [], "coverage": [],
                       "sourceIdentity": self.source, "sourceProof": {"swf": SWF, "sourceHashes": dict(BASIS)},
                       "parserCoverage": {"supportedNodes": 0, "unknownNodes": 0,
                                          "fixedReferencesComplete": False, "selection": "finite-layout-inventory"},
                       "complete": False, "runtimeAcceptance": False,
                       "runtimeContentBindingsVerified": False}

    def problem(self, reason, pointer, *, unknown=True, required=None):
        value = {"domain": "shared", "pointer": pointer, "reason": reason, "dynamic": True,
                 "sourceIdentity": dict(self.source)}
        if required:
            value["requiredReferences"] = required
        self.result["problems"].append(value)
        if unknown:
            self.result["parserCoverage"]["unknownNodes"] += 1

    def reference(self, logical, kind, pointer, consumer, **metadata):
        try:
            logical = _path(logical)
        except ValueError as exc:
            self.problem(str(exc), pointer)
            return
        context = dict(self.context)
        context.update({"kind": kind, "category": "shared"})
        if kind == "texture":
            context.update({"bucket": "Common", "collection": "common-view-ui-textures", "layer": "independent"})
        elif kind == "ui":
            context.update({"bucket": "FollowingLogic", "collection": "common-following-logic", "layer": "independent"})
        elif kind == "html":
            context.update({"bucket": "View", "collection": "common-view-rich-text", "layer": "independent"})
        reference = {"logical": logical, "kind": kind, "pointer": pointer, "domain": "shared",
                     "origin": self.kind + "-consumer", "context": context,
                     "definitionEvidence": {"logical": self.source["logical"],
                                            "sha256": self.source["sha256"], "sourcePointer": pointer,
                                            "consumer": consumer, "sourceHashes": dict(BASIS)}}
        reference.update(metadata)
        self.result["references"].append(reference)

    def text(self, value, pointer, **metadata):
        self.result["texts"].append({"text": value, "pointer": pointer,
                                     "sourceIdentity": dict(self.source), **metadata})

    def covered(self, pointer, **metadata):
        self.result["parserCoverage"]["supportedNodes"] += 1
        self.result["coverage"].append({"pointer": pointer, "status": "included", **metadata})


def _inspect_ui(data, report):
    if not isinstance(data, dict) or not isinstance(data.get("layouts"), list):
        raise ValueError("UI根需要实际layouts数组")
    for key in data:
        if key not in ("layouts", "timelines"):
            report.problem("UI根扩展字段尚缺当前消费证据", _pointer(report.pointer, key))
    layouts, ids, links = data["layouts"], {}, {}
    for i, layout in enumerate(layouts):
        at = _pointer(_pointer(report.pointer, "layouts"), i)
        if isinstance(layout, dict) and isinstance(layout.get("id"), str):
            if layout["id"] in ids:
                report.problem("UI布局id重复，当前findLayout首个命中而库存包含多个定义", _pointer(at, "id"))
            else:
                ids[layout["id"]] = i
    report.result["layoutIds"] = list(ids)
    requested = report.context.get("requiredLayouts")
    selected = None
    if requested is not None:
        if not isinstance(requested, list) or len(requested) > MAX_NODES or any(not isinstance(v, str) for v in requested):
            raise ValueError("UI requiredLayouts需要实际字符串ID数组")
        selected = set()
        todo = [(name, 0) for name in requested]
        while todo:
            name, depth = todo.pop()
            if name not in ids:
                report.problem("要求的UI内部布局不存在：" + name, _pointer(report.pointer, "requiredLayouts"),
                               required=[{"logical": report.source["logical"], "layoutId": name}])
                continue
            index = ids[name]
            if index in selected:
                continue
            if depth > MAX_DEPTH:
                report.problem("要求的UI内部布局引用深度超限", _pointer(report.pointer, "requiredLayouts"))
                continue
            selected.add(index)
            layout = layouts[index]
            children = layout.get("children")
            values = children.get("containers") if isinstance(children, dict) else None
            if isinstance(values, list):
                for child in values:
                    attributes = child.get("attributes") if isinstance(child, dict) else None
                    target = attributes.get("layout_id") if isinstance(attributes, dict) else None
                    if isinstance(target, str):
                        todo.append((target, depth + 1))
        report.result["parserCoverage"]["selection"] = "required-layouts-and-same-file-closure"
    report.result["selectedLayoutIds"] = [layout.get("id") for i, layout in enumerate(layouts)
                                        if isinstance(layout, dict) and (selected is None or i in selected)]
    for i, layout in enumerate(layouts):
        if selected is not None and i not in selected:
            continue
        at = _pointer(_pointer(report.pointer, "layouts"), i)
        if not isinstance(layout, dict) or not isinstance(layout.get("id"), str) or not isinstance(layout.get("children"), dict):
            report.problem("UI布局需要字符串id与children对象", at)
            continue
        name = layout["id"]
        links.setdefault(i, [])
        children = layout["children"]
        for group in children:
            if group not in ("bitmaps", "texts", "containers", "guides", "components"):
                report.problem("UI子节点组尚缺当前消费证据", _pointer(_pointer(at, "children"), group))
        for group in ("bitmaps", "texts", "containers", "guides", "components"):
            items = children.get(group)
            group_at = _pointer(_pointer(at, "children"), group)
            if not isinstance(items, list):
                # parseChildren directly consumes these three arrays.
                if group in ("bitmaps", "texts", "containers") or items is not None:
                    report.problem("UI子节点组需要数组", group_at)
                continue
            if group == "components":
                if items:
                    report.problem("当前UiProviderImpl不读取components，扩展组件消费与动态素材尚未确认", group_at)
                continue
            for j, item in enumerate(items):
                item_at = _pointer(group_at, j)
                if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
                    report.problem("UI子节点attributes需要对象", item_at)
                    continue
                attributes = item["attributes"]
                attrs_at = _pointer(item_at, "attributes")
                if group == "bitmaps":
                    kind = attributes.get("kind")
                    if not isinstance(kind, str):
                        report.problem("UI图片kind需要当前支持的字符串", _pointer(attrs_at, "kind"))
                        continue
                    if kind in ("simple", "slice", "fill"):
                        report.reference(attributes.get("path"), "texture", _pointer(attrs_at, "path"),
                            "UiProviderImpl.createImage -> UiImageFactroy.create -> ViewAssetContainer.getTexture",
                            lookup="exact-texture", preloadRequired=True)
                        report.covered(item_at, kind=kind)
                    elif kind == "dummy":
                        report.covered(item_at, kind=kind, resourceBehavior="no-path-read")
                        report.problem("dummy是运行时替换的图片占位；具体图片与填充来源尚未冻结",
                                       item_at, unknown=False)
                    else:
                        report.problem("当前UiImageFactroy不支持的图片kind：" + kind, _pointer(attrs_at, "kind"))
                elif group == "texts":
                    # The actual constructor creates TextField(...,"").
                    # The slot name is not a master text-table key.
                    report.text("", item_at, name=item.get("name"), status="runtime-bound",
                                consumer="UiText.constructor -> empty TextField; runtime set_text")
                    report.covered(item_at, kind="text-slot")
                    report.problem("UI文字先创建为空白；实际文字及内联图标由运行时set_text填入，不能凭name猜文字表",
                                   item_at, unknown=False)
                elif group == "containers":
                    target = attributes.get("layout_id")
                    if not isinstance(target, str):
                        report.problem("UI内部layout_id需要字符串", _pointer(attrs_at, "layout_id"))
                    else:
                        links[i].append((target, _pointer(attrs_at, "layout_id")))
                        report.covered(item_at, kind="internal-layout", target=target)
                else:
                    kind = attributes.get("guide_kind")
                    if not isinstance(kind, str) or kind not in ("point", "rectangle"):
                        report.problem("UI参考点guide_kind不是当前point/rectangle", _pointer(attrs_at, "guide_kind"))
                    else:
                        report.covered(item_at, kind="guide", resourceBehavior="no-resource-read")
    # Check actual same-file links without recursing into every shared layout.
    graph = {}
    for index, references in links.items():
        graph[index] = []
        for target, pointer in references:
            if target not in ids:
                report.problem("UI内部布局不存在：" + target, pointer,
                               required=[{"logical": report.source["logical"], "layoutId": target}])
            else:
                graph[index].append((ids[target], pointer))
    states = {}
    for start in graph:
        if states.get(start):
            continue
        states[start] = 1
        stack = [(start, iter(graph[start]))]
        while stack:
            node, edges = stack[-1]
            edge = next(edges, None)
            if edge is None:
                states[node] = 2
                stack.pop()
                continue
            target, pointer = edge
            if states.get(target) == 1:
                report.problem("UI内部布局引用成环；当前build会递归，不能视为闭合", pointer)
            elif not states.get(target):
                if len(stack) >= MAX_DEPTH:
                    report.problem("UI内部布局引用链超过有界深度", pointer)
                    continue
                states[target] = 1
                stack.append((target, iter(graph.get(target, ()))))
    timelines = data.get("timelines")
    if timelines is not None and not isinstance(timelines, dict):
        report.problem("UI内嵌timelines需要对象", _pointer(report.pointer, "timelines"))
    elif timelines:
        report.problem("UI内嵌时间轴的实际播放及声音消费者仍待核；原始时序保留",
                       _pointer(report.pointer, "timelines"))


def _strip_text(value):
    return value.replace("\n", "").replace("\r", "").replace("\t", "").strip()


def _element_text(element):
    pieces = []
    if element.text:
        pieces.append(element.text)
    for child in element:
        clone = copy.copy(child)
        clone.tail = None
        pieces.append(ET.tostring(clone, encoding="unicode"))
        if child.tail:
            pieces.append(child.tail)
    return "".join(_strip_text(piece) for piece in pieces)


def _html_image(src, report, at):
    if not isinstance(src, str):
        report.problem("rich-text图片缺src字符串", at)
    elif src.startswith("file://"):
        # Current resolveSource uses protocol.length + 2, then split('.')[0].
        path = src[7:].split(".")[0]
        if path.startswith("character/") and "/ui/skill_cutin_" in path:
            report.problem("此本地rich-text图片属于平台ATF/PNG条件素材，需真实assetReadKind才能确定物理文件", at,
                           required=[{"logical": path, "kind": "platform-texture"}])
            return
        report.reference(path, "texture", at,
                         "RichTextImageLoader.resolveSource LocalAsset -> ViewAssetCache.setTexture",
                         lookup="standalone-file-texture", runtimeLoad=True)
    elif src.startswith("https:"):
        report.problem("rich-text图片由HTTPS在运行时下载；本地冻结素材不能证明远程资源",
                       at, required=[{"url": src, "kind": "remote-image"}])
    else:
        report.problem("当前rich-text图片只支持file://本地素材或https:下载；裸路径及其他协议不能猜为PNG", at)


def _html_button(src, report, at):
    if not isinstance(src, str):
        report.problem("rich-text按钮缺src字符串", at)
        return
    parts = src.split("/")
    if parts[0] != "button":
        _html_image(src, report, at)
        return
    name = parts[1] if len(parts) > 1 else "base"
    enabled = {"base": "highlight", "negative": "negative", "positive": "positive", "white": "pure_white"}
    if name not in enabled:
        report.problem("当前rich-text内置按钮类型不支持：" + name, at)
        return
    # Box factory and DownBlurFactory reuse this same actual UI input.
    layouts = ["layout/box_background/" + enabled[name], "layout/box_background/disable"]
    if name != "white":
        layouts.append("layout/box_down_blur/standard")
    report.reference("scene/common_ui_bundled/general_button", "ui", at,
        "RichTextLayoutButton.addButton -> current boot presets -> BoxButtonBackgroundFactory/DownBlurFactory",
        requiredLayouts=layouts, selection="finite-button-layout-inventory")
    if name == "white":
        report.problem("white按钮downBlurType=3的具体资源消费仍待核", at + "/downBlurType/3")


def _inspect_html(text, report):
    # The preserved documents contain this exact harmless declaration.
    # Reject other DTDs/entities instead of letting an XML parser expand them.
    text = text.replace("<!DOCTYPE html/>", "")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError("rich-text仅接受已证无实体DOCTYPE，拒绝其他DTD或ENTITY声明")
    if re.search(r"<\?xml\b", text, re.IGNORECASE):
        raise ValueError("rich-text XML声明/编码语义尚未冻结")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    document = ET.fromstring("<_document>" + text + "</_document>", parser=parser)
    stack = [(document, 0)]
    nodes = 0
    while stack:
        element, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("rich-text节点或嵌套超限")
        stack.extend((child, depth + 1) for child in element)
    html = next((e for e in document if e.tag == "html"), None)
    body = next((e for e in html if e.tag == "body"), None) if html is not None else None
    if body is None:
        raise ValueError("当前rich-text需要首个顶层html中的首个直属body")
    recursive = {"div", "li", "ol", "table", "td", "th", "tr", "ul"}
    plain = {"p", "h1", "h2", "h3", "br", "hr", "img"}
    root_at = _pointer(report.pointer, "html")

    def content(element, at, xml_at, depth):
        index = 0
        def pcdata(value, source):
            nonlocal index
            if value and _strip_text(value):
                node_at = _pointer(_pointer(at, "node"), index)
                report.text(_strip_text(value), _pointer(node_at, "text"), status="static",
                            xmlPointer=source)
                report.covered(node_at, kind="_Text_")
                index += 1
        pcdata(element.text, xml_at + "/text()")
        for position, child in enumerate(element):
            tag = child.tag
            child_xml = xml_at + "/" + str(tag) + "[" + str(position) + "]"
            node_at = _pointer(_pointer(at, "node"), index)
            accepted = isinstance(tag, str) and (tag in recursive or tag in plain)
            button = False
            child_for_fields = child
            if tag == "a":
                # Flash Xml.firstChild() may be leading PCData/comment, not img.
                first = next(iter(child), None) if not child.text else None
                button = first is not None and first.tag == "img"
                accepted = button
                if button:
                    child_for_fields = first
            if accepted:
                report.covered(node_at, kind="Button" if button else tag)
                value = child_for_fields.get("alt")
                if value is None:
                    value = _element_text(child_for_fields)
                if value:
                    report.text(value, _pointer(node_at, "text"), status="static", xmlPointer=child_xml)
                if button:
                    src = child_for_fields.get("button", child_for_fields.get("src"))
                    _html_button(src, report, _pointer(node_at, "src"))
                    href = child.get("scene", child.get("href"))
                    if href is not None:
                        report.result["coverage"].append({"pointer": _pointer(node_at, "href"), "status": "navigation",
                                                          "value": href, "resourceBehavior": "not-an-image-reference"})
                elif tag == "img":
                    _html_image(child.get("src"), report, _pointer(node_at, "src"))
                if tag in recursive:
                    content(child, node_at, child_xml, depth + 1)
                index += 1
            else:
                report.result["coverage"].append({"pointer": node_at, "status": "ignored-by-current-parser",
                                                  "tag": str(tag), "xmlPointer": child_xml})
            pcdata(child.tail, child_xml + "/tail()")

    content(body, root_at, "/html/body", 0)
    report.result["parserCoverage"]["selection"] = "first-top-html-first-direct-body"
    report.result["coverage"].append({"pointer": _pointer(report.pointer, "style"), "status": "included",
                                      "resourceBehavior": "getLayoutData returns empty style; head/link is not read"})


def resolve_ui_resources(logical, raw, kind="ui", context=None, pointer=""):
    """Return known consumers and precise gaps from one exact physical file."""
    # The caller picks the physical codec; conflicting alternatives must remain
    # a graph problem there, not be inferred from arbitrary bytes here.
    fallback = {"references": [], "problems": [], "texts": [], "coverage": [],
                "complete": False, "runtimeAcceptance": False}
    try:
        if not isinstance(raw, bytes) or len(raw) > LIMIT:
            raise ValueError("UI输入需要有界原始bytes")
        if not isinstance(pointer, str) or not isinstance(context, (dict, type(None))):
            raise ValueError("UI来源pointer/context结构无效")
        physical = physical_path(logical, kind)
        report = _Report(physical, raw, kind, context, pointer)
        if kind == "ui":
            if physical.endswith(".ui.amf3.deflate"):
                data = _amf(_inflate(raw))
            else:
                data = _json(raw)
            _tree_budget(data)
            _inspect_ui(data, report)
        else:
            decoded = _inflate(raw) if physical.endswith(".html.deflate") else raw
            _inspect_html(decoded.decode("utf-8-sig"), report)
        coverage = report.result["parserCoverage"]
        coverage["fixedReferencesComplete"] = coverage["unknownNodes"] == 0
        coverage["status"] = "included" if coverage["fixedReferencesComplete"] else "pending"
        return report.result
    except (ValueError, TypeError, IndexError, KeyError, UnicodeError, RecursionError, zlib.error, ET.ParseError) as exc:
        result = report.result if "report" in locals() else fallback
        result["problems"].append({"domain": "shared", "pointer": pointer,
                                   "reason": "UI资源解析待核：" + str(exc), "dynamic": True})
        if "parserCoverage" in result:
            result["parserCoverage"]["status"] = "pending"
            result["parserCoverage"]["unknownNodes"] += 1
            result["parserCoverage"]["fixedReferencesComplete"] = False
        return result
