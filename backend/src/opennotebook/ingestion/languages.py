"""Source-code detection by file name. Grammars (tree-sitter) exist for the main languages; other code and
configuration files are indexed as text with line anchors."""

from __future__ import annotations

# extension -> language name; the grammar module is in GRAMMARS when structure-aware parsing is available
EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".cs": "c_sharp",
    ".php": "php",
    ".rb": "ruby",
    # without a bundled grammar: indexed by lines
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".m": "objective-c",
    ".dart": "dart",
    ".sql": "sql",
    ".vue": "vue",
    ".svelte": "svelte",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "conf",
    ".xml": "xml",
    ".proto": "protobuf",
    ".gradle": "groovy",
    ".groovy": "groovy",
    ".cmake": "cmake",
    ".mk": "make",
    ".ld": "linker-script",
    ".s": "assembly",
    ".asm": "assembly",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".vhd": "vhdl",
    ".tf": "terraform",
    ".ps1": "powershell",
    ".bat": "batch",
}

FILENAMES: dict[str, str] = {
    "makefile": "make",
    "gnumakefile": "make",
    "dockerfile": "dockerfile",
    "cmakelists.txt": "cmake",
    "kconfig": "kconfig",
    "jenkinsfile": "groovy",
    "vagrantfile": "ruby",
    "gemfile": "ruby",
    "rakefile": "ruby",
}

SHEBANGS = {"python": "python", "bash": "bash", "sh": "bash", "node": "javascript", "ruby": "ruby"}

# language -> (module, function returning the grammar)
GRAMMARS: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "java": ("tree_sitter_java", "language"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "bash": ("tree_sitter_bash", "language"),
    "c_sharp": ("tree_sitter_c_sharp", "language"),
    "php": ("tree_sitter_php", "language_php"),
    "ruby": ("tree_sitter_ruby", "language"),
}


def detect_language(filename: str, head: bytes) -> str | None:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in FILENAMES:
        return FILENAMES[name]
    if name.startswith("dockerfile"):
        return "dockerfile"
    dot = name.rfind(".")
    if dot > 0 and name[dot:] in EXTENSIONS:
        return EXTENSIONS[name[dot:]]
    if head.startswith(b"#!"):
        line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
        for word, lang in SHEBANGS.items():
            if word in line:
                return lang
    return None
