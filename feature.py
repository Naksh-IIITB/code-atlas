import ast
import base64
import io
import os
import re
import stat
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from core import DATA, db, rows, rank, chat

PORT = 8502
LANGUAGES = {".py":"Python", ".c":"C", ".h":"C", ".cpp":"C++", ".cc":"C++", ".hpp":"C++",
             ".java":"Java", ".js":"JavaScript", ".jsx":"JavaScript", ".ts":"TypeScript", ".tsx":"TypeScript",
             ".md":"Markdown", ".toml":"TOML", ".yaml":"YAML", ".yml":"YAML", ".rs":"Rust", ".go":"Go"}
IGNORED = {"node_modules", "vendor", "dist", "build", "target", "venv", "__pycache__", "coverage"}
SENSITIVE = re.compile(r"(?i)(credential|secret|\.pem$|\.key$|\.p12$|id_ed25519|id_rsa)")
SECRET_CONTENT = re.compile(r"-----BEGIN [^-]+PRIVATE KEY-----|gh[pousr]_[a-zA-Z0-9]{25,}|AKIA[A-Z0-9]{16}|(?i:api[_-]?key|password|secret)\s*[:=]\s*['\"][^'\"]{12,}['\"]")


def initialize():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS repos(id INTEGER PRIMARY KEY, name TEXT, origin TEXT, commits TEXT);
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, repo INTEGER REFERENCES repos ON DELETE CASCADE,
          path TEXT, language TEXT, code TEXT, UNIQUE(repo,path));
        """)


def acceptable(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and not any(part.startswith(".") or part in IGNORED or SENSITIVE.search(part)
            for part in path.parts) and path.suffix.lower() in LANGUAGES)


def git(folder, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                           "-C", str(folder), *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=90, env=env).stdout


def local_files(folder):
    root = folder.resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise ValueError("Choose the root of a local Git repository.")
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode(errors="replace").split("\0")
    for name in dict.fromkeys(paths):
        path = root / name
        if acceptable(name) and not path.is_symlink() and path.is_file() and root in path.resolve().parents and path.stat().st_size <= 140_000:
            yield name, path.read_bytes()


def archive_files(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for item in archive.infolist():
            if acceptable(item.filename) and item.file_size <= 140_000 and not stat.S_ISLNK(item.external_attr >> 16):
                yield item.filename, archive.read(item)


def index(name, origin, files, commits=""):
    with db() as con:
        repo = con.execute("INSERT INTO repos(name,origin,commits) VALUES(?,?,?)", (name,origin,commits)).lastrowid
        count, total = 0, 0
        for path, raw in files:
            if count >= 1500 or total + len(raw) > 20_000_000:
                break
            if b"\0" in raw:
                continue
            code = raw.decode("utf-8", errors="replace")
            if SECRET_CONTENT.search(code):
                continue
            cur = con.execute("INSERT OR IGNORE INTO files(repo,path,language,code) VALUES(?,?,?,?)",
                              (repo,path,LANGUAGES[Path(path).suffix.lower()],code))
            count += cur.rowcount
            total += len(raw)
        if not count:
            raise ValueError("No indexable source files found.")
    return {"id":repo,"files":count}


def inspect(file):
    code = file["code"]
    symbols, imports, calls, inheritance = [], [], [], []
    if file["language"] == "Python":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return symbols, imports, calls, inheritance
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                function = not isinstance(node, ast.ClassDef)
                end = getattr(node, "end_lineno", node.lineno)
                complexity = 1 + sum(isinstance(x, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp,
                                                      ast.ExceptHandler, ast.comprehension))
                                     for x in ast.walk(node)) if function else None
                symbols.append({"name":node.name,"line":node.lineno,"end":end,"complexity":complexity,
                                "kind":"function" if function else "class"})
                if function:
                    calls.extend([node.name, ast.unparse(child.func)] for child in ast.walk(node) if isinstance(child, ast.Call))
                else:
                    inheritance.extend([node.name, ast.unparse(base)] for base in node.bases)
            elif isinstance(node, ast.Import):
                imports.extend(module.name for module in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append("."*node.level+(node.module or ""))
    else:
        declarations = re.compile(r"\b(class|interface|struct|enum|function)\s+([A-Za-z_]\w*)|^\s*(?:[\w:*&<>]+\s+)+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{")
        for number, line in enumerate(code.splitlines(), 1):
            match = declarations.search(line)
            if match and match[3] not in {"if","while","for","switch","return"}:
                symbols.append({"name":match[2] or match[3],"line":number,"end":number,
                                "kind":match[1] or "function","complexity":None})
            dependency = re.search(r'^\s*#\s*include\s*[<\"]([^>\"]+)|\bfrom\s+[\'\"]([^\'\"]+)|^\s*import\s+([\w.]+)',line)
            if dependency:
                imports.append(next(value for value in dependency.groups() if value))
    return symbols, imports, calls, inheritance


def overview(files):
    result = {"languages":Counter(), "symbols":[], "edges":[], "files":[], "duplicates":[], "entrypoints":[]}
    duplicates = defaultdict(list)
    for file in files:
        symbols, imports, calls, inheritance = inspect(file)
        path = file["path"]
        result["languages"][file["language"]] += 1
        result["files"].append({k:v for k,v in file.items() if k != "code"})
        result["symbols"].extend(dict(symbol,file=path) for symbol in symbols)
        result["edges"].extend({"from":path,"to":item,"kind":"import"} for item in sorted(set(imports)))
        result["edges"].extend({"from":f"{path} · {source}","to":target,"kind":"call"} for source,target in sorted(set(map(tuple,calls))))
        result["edges"].extend({"from":f"{path} · {source}","to":target,"kind":"inherits"} for source,target in inheritance)
        if re.search(r"__name__\s*==\s*['\"]__main__|\b(?:int|void)\s+main\s*\(",file["code"]):
            result["entrypoints"].append(path)
        if len(file["code"]) >= 80:
            duplicates[file["code"].strip()].append(path)
    result["duplicates"] = [group for group in duplicates.values() if len(group)>1]
    return result


def matches(query, files, semantic=False, embedding=None):
    candidates = []
    for item in files:
        lines = item["code"].splitlines()
        for start in range(0,len(lines),32):
            end = min(start+40,len(lines))
            candidates.append({"path":item["path"],"start":start+1,"end":end,
                               "text":"\n".join(lines[start:end])[:2400]})
    found = rank(query,candidates)
    if semantic:
        found = rank(query,found[:120],True,embedding)
    return [item for item in found if item["score"] > 0][:8]


def ask(p, files):
    found = matches(p["query"], files, p.get("semantic"), p.get("embedding"))
    if not found and len(files) == 1:
        item = files[0]
        found = [{"path":item["path"],"start":1,"end":20,"text":"\n".join(item["code"].splitlines()[:20])}]
    yield {"sources":found}
    evidence = "\n\n".join(f"[S{i}] {x['path']}:{x['start']}-{x['end']}\n{x['text']}" for i,x in enumerate(found[:5],1))
    for token in chat(p.get("prompt","Explain the repository question.")+"\n"+p["query"],evidence,p.get("model")):
        yield {"token":token}


def handle(action,p,post):
    if not post and action == "repos":
        with db() as con:
            return rows(con,"SELECT * FROM repos ORDER BY id DESC")
    if not post:
        raise ValueError("Unknown action.")
    if action == "zip":
        raw = base64.b64decode(p["data"], validate=True)
        return index(Path(p["name"]).stem,"ZIP",archive_files(raw))
    if action == "local":
        folder = Path(p["path"]).expanduser()
        entries = local_files(folder)
        try:
            commits = git(folder,"log","-20","--format=%h %ad %s","--date=short").decode(errors="replace")
        except subprocess.CalledProcessError:
            commits = ""
        return index(folder.name,str(folder.resolve()),entries,commits)
    if action == "clone":
        import tempfile
        url = urlsplit(p["url"])
        if url.scheme != "https" or url.netloc != "github.com" or not re.fullmatch(r"/[\w.-]+/[\w.-]+/?",url.path) or url.query or url.fragment:
            raise ValueError("Enter a public HTTPS GitHub repository URL.")
        with tempfile.TemporaryDirectory() as temp:
            try:
                git(temp,"-c","protocol.file.allow=never","clone","--depth","30","--no-recurse-submodules","--",p["url"],"repo")
            except subprocess.CalledProcessError as error:
                raise ValueError(error.stderr.decode(errors="replace")) from error
            folder = Path(temp)/"repo"
            commits = git(folder,"log","-20","--format=%h %ad %s","--date=short").decode(errors="replace")
            return index(url.path.strip("/").split("/")[-1].removesuffix(".git"),p["url"],local_files(folder),commits)
    with db() as con:
        repo = int(p["repo"])
        if action == "delete":
            con.execute("DELETE FROM repos WHERE id=?",(repo,))
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='vectors'").fetchone():
                con.execute("DELETE FROM vectors")
            return {"ok":True}
        files = rows(con,"SELECT * FROM files WHERE repo=? ORDER BY path",(repo,))
    if action == "overview":
        return overview(files)
    if p.get("path"):
        files = [item for item in files if item["path"] == p["path"]]
    if action == "source":
        if not files or not p.get("path"):
            raise ValueError("Source file missing.")
        return files[0]
    if action == "search":
        return matches(p["query"],files,p.get("semantic"),p.get("embedding"))
    if action == "ask":
        return ask(p,files)
    raise ValueError("Unknown action.")
