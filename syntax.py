"""Tree-sitter structural analysis for supported non-Python source files."""
from functools import lru_cache
from importlib import import_module
from pathlib import Path

GRAMMARS = {
    "C": ("tree_sitter_c", "language"), "C++": ("tree_sitter_cpp","language"),
    "Java": ("tree_sitter_java","language"), "JavaScript": ("tree_sitter_javascript","language"),
    "TypeScript": ("tree_sitter_typescript","language_typescript"),
}
FUNCTIONS = {"function_definition","function_declaration","method_declaration","constructor_declaration",
             "method_definition","generator_function_declaration","function_expression","arrow_function"}
CLASSES = {"class_declaration","interface_declaration","class_specifier","struct_specifier","enum_declaration",
           "record_declaration","enum_specifier","abstract_class_declaration"}
IMPORTS = {"import_declaration","import_statement","preproc_include","export_statement"}
CALLS = {"call_expression","method_invocation","object_creation_expression","new_expression"}
BRANCHES = {"if_statement","for_statement","for_in_statement","enhanced_for_statement","while_statement","do_statement",
            "do_while_statement","conditional_expression","ternary_expression","catch_clause","case_statement","switch_case"}
IDENTS = {"identifier","type_identifier","field_identifier","property_identifier","operator_name",
          "destructor_name","qualified_identifier"}


@lru_cache(maxsize=8)
def grammar(language, tsx):
    from tree_sitter import Language
    module, factory = GRAMMARS[language]
    return Language(getattr(import_module(module), "language_tsx" if tsx else factory)())


def tree_sitter_inspect(file):
    language = file["language"]
    if language not in GRAMMARS:
        return None
    try:
        from tree_sitter import Parser
        parser = Parser(grammar(language,Path(file["path"]).suffix == ".tsx"))
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    raw = file["code"].encode()
    root = parser.parse(raw).root_node
    symbols, imports, calls, inheritance = [], [], [], []

    def source(node):
        return raw[node.start_byte:node.end_byte].decode(errors="replace").strip() if node else ""

    def declarator_name(node):
        if node is None:
            return ""
        if node.type in IDENTS:
            return source(node)
        named = node.child_by_field_name("name") or node.child_by_field_name("declarator")
        if named:
            return declarator_name(named)
        for child in node.named_children:
            if "declarator" in child.type or child.type in IDENTS:
                value = declarator_name(child)
                if value:
                    return value
        return ""

    stack = [(root,None)]
    while stack:
        node, owner = stack.pop()
        kind = node.type
        if kind in FUNCTIONS or kind in CLASSES:
            name = declarator_name(node.child_by_field_name("name") or node.child_by_field_name("declarator"))
            if not name and node.parent and node.parent.type in {"variable_declarator","pair","field_definition"}:
                name = source(node.parent.child_by_field_name("name") or node.parent.child_by_field_name("key")
                              or node.parent.child_by_field_name("property"))
            if name:
                owner = None
                entry = {"name":name,"line":node.start_point.row+1,"end":node.end_point.row+1,
                         "kind":"function" if kind in FUNCTIONS else "type","complexity":None}
                symbols.append(entry)
                if kind in FUNCTIONS:
                    entry["complexity"] = 1
                    owner = entry
                if kind in CLASSES:
                    for child in node.named_children:
                        if child.type in {"superclass","super_interfaces","extends_interfaces","class_heritage","base_class_clause"}:
                            inheritance.append([name,source(child).lstrip(": ")])
        if kind in IMPORTS:
            dependency = node.child_by_field_name("source") or node.child_by_field_name("path")
            value = source(dependency).strip("'\"<>") if dependency else ""
            if not value and kind == "import_declaration":
                value = source(node).removeprefix("import ").rstrip(";")
            if value:
                imports.append(value)
        if owner is not None:
            if kind in BRANCHES:
                owner["complexity"] += 1
            if kind in CALLS:
                target = node.child_by_field_name("function") or node.child_by_field_name("name") or node.child_by_field_name("constructor") or node.child_by_field_name("type")
                receiver = node.child_by_field_name("object") if kind == "method_invocation" else None
                value = (source(receiver) + "." if receiver else "") + source(target)
                if value and len(value) <= 140:
                    calls.append([owner["name"],value])
        stack.extend((child,owner) for child in reversed(node.named_children))
    return symbols, imports, calls, inheritance
