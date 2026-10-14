"""Static argparse surface extraction (stdlib ast only).

Shared by check_docs_drift.py and check_public_surface.py. Understands the
argparse style used by tools/workbench.py and harness-core/harness/cli.py:

    p = argparse.ArgumentParser(...)
    p.add_argument("--target", ...)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")                      # bare Expr
    i = sub.add_parser("install")                 # Assign -> parser var
    i.add_argument("--scope", choices=[...])
    rec = sub.add_parser("feedback").add_subparsers(dest="fcmd")   # chained
    r = rec.add_parser("record")
    r.add_argument("--cause", required=True)

Output:
  {"global_flags": {"--target": {"choices": None}},
   "commands": {"install": {"flags": {"--scope": {"choices": [...]}},
                            "positionals": {"cap_cmd": {"choices": [...]}}},
                "feedback record": {...}, ...}}

Extraction is deliberately loud: if no subparsers are found the result is
empty and callers must treat that as an error, never as "no CLI".
"""
import ast
from pathlib import Path


def _const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
        return node.value
    return None


def _const_list(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for elt in node.elts:
            v = _const(elt)
            if v is None:
                return None
            out.append(str(v))
        return out
    return None


def _kwargs(call):
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _is_argparse_ctor(call):
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr == "ArgumentParser"
            and isinstance(func.value, ast.Name) and func.value.id == "argparse")


def extract_cli_surface(script: Path) -> dict:
    tree = ast.parse(Path(script).read_text(encoding="utf-8"),
                     filename=str(script))
    root_vars: set[str] = set()
    parser_vars: dict[str, tuple[str, ...]] = {}     # var holding a parser -> cmd path
    subparser_vars: dict[str, tuple[str, ...]] = {}  # var holding subparsers -> base path
    commands: dict[tuple[str, ...], dict] = {}
    global_flags: dict[str, dict] = {}

    def cmd(key):
        return commands.setdefault(key, {"flags": {}, "positionals": {}})

    def handle_add_argument(call, owner_path):
        kw = _kwargs(call)
        choices = _const_list(kw["choices"]) if "choices" in kw else None
        if owner_path is None:
            target = global_flags
        else:
            target = None
        first = _const(call.args[0]) if call.args else None
        if first is None:
            return
        entry = {"choices": choices}
        if str(first).startswith("--"):
            if owner_path is None:
                global_flags[str(first)] = entry
            else:
                cmd(owner_path)["flags"][str(first)] = entry
        elif owner_path is not None:
            cmd(owner_path)["positionals"][str(first)] = entry

    def add_parser_path(call):
        """Resolve X.add_parser("name") -> (base_path, name) or None."""
        if not call.args:
            return None
        name = _const(call.args[0])
        owner = call.func.value
        if name is None or not isinstance(owner, ast.Name):
            return None
        if owner.id in subparser_vars:
            return subparser_vars[owner.id], str(name)
        return None

    for node in ast.walk(tree):
        call = None
        targets = []
        if isinstance(node, ast.Assign):
            call = node.value
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.Expr):
            call = node.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        attr = call.func.attr

        if _is_argparse_ctor(call):
            root_vars.update(targets)
            continue

        if attr == "add_argument":
            owner = call.func.value
            if isinstance(owner, ast.Name):
                if owner.id in root_vars:
                    handle_add_argument(call, None)
                elif owner.id in parser_vars:
                    handle_add_argument(call, parser_vars[owner.id])
            continue

        if attr == "add_parser":
            resolved = add_parser_path(call)
            if resolved:
                base, name = resolved
                path = base + (name,)
                cmd(path)
                for t in targets:
                    parser_vars[t] = path
            continue

        if attr == "add_subparsers":
            parent = call.func.value
            base = None
            if isinstance(parent, ast.Name):
                if parent.id in root_vars:
                    base = ()
                elif parent.id in subparser_vars:
                    base = subparser_vars[parent.id]
            elif isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) \
                    and parent.func.attr == "add_parser":
                resolved = add_parser_path(parent)
                if resolved:
                    b, name = resolved
                    base = b + (name,)
                    cmd(base)
            if base is not None:
                for t in targets:
                    subparser_vars[t] = base
            continue

    out = {"global_flags": global_flags,
           "commands": {" ".join(k): {"flags": v["flags"],
                                      "positionals": v["positionals"]}
                         for k, v in sorted(commands.items()) if k}}
    return out


def check_invocation(surface: dict, tokens: list[str]) -> list[str]:
    """Validate a documented invocation against the extracted surface.

    tokens: argv after the script, e.g. ["feedback", "record", "--cause"].
    Returns a list of problems (empty = OK).
    """
    problems = []
    path = []
    i = 0
    commands = surface["commands"]
    while i < len(tokens) and not tokens[i].startswith("-"):
        probe = " ".join(path + [tokens[i]])
        if probe in commands:
            path.append(tokens[i])
            i += 1
        else:
            break
    key = " ".join(path)
    if not path:
        return [f"unknown command: {' '.join(tokens[:2]) or '(none)'}"]
    if key not in commands:
        return [f"unknown command path: {key}"]
    spec = commands[key]
    positionals = list(spec["positionals"].values())
    pos_idx = 0
    for tok in tokens[i:]:
        if tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if name not in spec["flags"] and name not in surface["global_flags"]:
                problems.append(f"{key}: unknown flag {tok}")
        elif tok.startswith("-"):
            problems.append(f"{key}: unknown short flag {tok}")
        else:
            # positional value: must satisfy choices if the positional has any
            if pos_idx < len(spec["positionals"]):
                pspec = positionals[pos_idx]
                pos_idx += 1
                if pspec.get("choices") and tok not in pspec["choices"]:
                    problems.append(f"{key}: '{tok}' not in choices {pspec['choices']}")
            # extra bare tokens beyond declared positionals are tolerated
            # (values for flags like --cause "text" arrive as separate tokens
            # in docs; we cannot distinguish them statically)
    return problems
