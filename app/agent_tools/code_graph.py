#!/usr/bin/env python3
"""Code graph builder for reachability analysis.

Builds a deterministic map of code structure: symbols, calls, imports, and entry points.
This enables reachability analysis to filter vulnerabilities by whether they're actually
callable from the application's execution paths.

Inspired by VVAH's deterministic stages (S0-S2) for efficient, model-free analysis.
"""
import ast
import json
import os
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, asdict


@dataclass
class FileNode:
    """Represents a file in the code graph."""
    path: str
    imports: List[str]
    functions: List[str]
    classes: List[str]
    calls: List[str]
    is_entry_point: bool
    routes: List[str]  # Web framework routes (Flask, FastAPI)


@dataclass
class CodeGraph:
    """Complete code graph for a repository."""
    files: Dict[str, FileNode]
    entry_points: List[str]
    import_map: Dict[str, List[str]]  # module -> files that import it
    function_map: Dict[str, str]  # function name -> file that defines it
    call_graph: Dict[str, List[str]]  # file -> files it calls into


class PythonCodeGraphBuilder:
    """Builds code graph for Python repositories."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self.files: Dict[str, FileNode] = {}
        self.entry_points: List[str] = []

    def build(self) -> CodeGraph:
        """Build complete code graph by analyzing all Python files."""
        # Phase 1: Analyze each file
        for py_file in self.repo_path.rglob("*.py"):
            # Skip test files and virtual environments
            if self._should_skip(py_file):
                continue

            try:
                file_node = self._analyze_file(py_file)
                relative_path = str(py_file.relative_to(self.repo_path))
                self.files[relative_path] = file_node

                if file_node.is_entry_point:
                    self.entry_points.append(relative_path)
            except Exception as e:
                # Skip files that can't be parsed
                continue

        # Phase 2: Build cross-file maps
        import_map = self._build_import_map()
        function_map = self._build_function_map()
        call_graph = self._build_call_graph(function_map)

        return CodeGraph(
            files=self.files,
            entry_points=self.entry_points,
            import_map=import_map,
            function_map=function_map,
            call_graph=call_graph
        )

    def _should_skip(self, file_path: Path) -> bool:
        """Check if file should be skipped during analysis."""
        skip_patterns = [
            'test_', 'tests/', '__pycache__/', '.venv/', 'venv/',
            'site-packages/', '.tox/', 'build/', 'dist/'
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in skip_patterns)

    def _analyze_file(self, file_path: Path) -> FileNode:
        """Analyze a single Python file and extract structure."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            # Return empty node for files with syntax errors
            return FileNode(
                path=str(file_path.relative_to(self.repo_path)),
                imports=[], functions=[], classes=[], calls=[],
                is_entry_point=False, routes=[]
            )

        # Extract imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        # Extract function definitions
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)

        # Extract class definitions
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)

        # Extract function calls
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)

        # Detect entry points
        is_entry_point = self._is_entry_point(content, tree)

        # Detect web framework routes
        routes = self._extract_routes(tree)

        return FileNode(
            path=str(file_path.relative_to(self.repo_path)),
            imports=list(set(imports)),
            functions=list(set(functions)),
            classes=list(set(classes)),
            calls=list(set(calls)),
            is_entry_point=is_entry_point,
            routes=routes
        )

    def _is_entry_point(self, content: str, tree: ast.AST) -> bool:
        """Determine if file is an entry point."""
        # Check for if __name__ == "__main__"
        if 'if __name__' in content and '__main__' in content:
            return True

        # Check for web framework app creation
        web_patterns = [
            'Flask(__name__)', 'FastAPI()', 'app.run()',
            'uvicorn.run', 'gunicorn', 'Django'
        ]
        if any(pattern in content for pattern in web_patterns):
            return True

        return False

    def _extract_routes(self, tree: ast.AST) -> List[str]:
        """Extract web framework route definitions."""
        routes = []
        for node in ast.walk(tree):
            # Flask: @app.route('/path')
            # FastAPI: @app.get('/path'), @app.post('/path')
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Attribute):
                            if decorator.func.attr in ['route', 'get', 'post', 'put', 'delete', 'patch']:
                                # Extract route path from decorator arguments
                                if decorator.args:
                                    if isinstance(decorator.args[0], ast.Constant):
                                        routes.append(decorator.args[0].value)
        return routes

    def _build_import_map(self) -> Dict[str, List[str]]:
        """Build map of which files import which modules."""
        import_map: Dict[str, List[str]] = {}
        for file_path, file_node in self.files.items():
            for import_name in file_node.imports:
                if import_name not in import_map:
                    import_map[import_name] = []
                import_map[import_name].append(file_path)
        return import_map

    def _build_function_map(self) -> Dict[str, str]:
        """Build map of which file defines which function."""
        function_map: Dict[str, str] = {}
        for file_path, file_node in self.files.items():
            for function_name in file_node.functions:
                # If multiple files define same function, keep first
                if function_name not in function_map:
                    function_map[function_name] = file_path
        return function_map

    def _build_call_graph(self, function_map: Dict[str, str]) -> Dict[str, List[str]]:
        """Build call graph: which files call into which other files."""
        call_graph: Dict[str, List[str]] = {}

        for file_path, file_node in self.files.items():
            called_files = set()

            # For each function call in this file
            for call_name in file_node.calls:
                # Find which file defines this function
                if call_name in function_map:
                    target_file = function_map[call_name]
                    if target_file != file_path:  # Don't include self-calls
                        called_files.add(target_file)

            call_graph[file_path] = list(called_files)

        return call_graph


class ReachabilityAnalyzer:
    """Analyzes if vulnerable code is reachable from entry points."""

    def __init__(self, code_graph: CodeGraph):
        self.graph = code_graph
        self._reachable_cache: Optional[Set[str]] = None

    def analyze_vulnerability(self, vuln_file: str, vuln_function: Optional[str] = None) -> Dict:
        """
        Analyze if a vulnerability is reachable from application entry points.

        Args:
            vuln_file: Relative path to file containing vulnerability
            vuln_function: Optional function name where vulnerability exists

        Returns:
            Dict with reachability analysis results
        """
        # Normalize path separators
        vuln_file = vuln_file.replace('\\', '/')

        # Check if file exists in graph
        if vuln_file not in self.graph.files:
            return {
                "vulnerable_code": f"{vuln_file}:{vuln_function or 'unknown'}",
                "reachable": False,
                "confidence": "LOW",
                "reason": "File not found in code graph (may be test/vendored code)",
                "call_chain": []
            }

        # Get all reachable files
        reachable_files = self._get_reachable_files()

        # Check if vulnerable file is reachable
        is_reachable = vuln_file in reachable_files

        # Build call chain if reachable
        call_chain = []
        if is_reachable:
            call_chain = self._find_call_chain(vuln_file)

        # Determine confidence
        confidence = self._determine_confidence(vuln_file, vuln_function, is_reachable)

        # Generate reason
        reason = self._generate_reason(vuln_file, vuln_function, is_reachable, call_chain)

        return {
            "vulnerable_code": f"{vuln_file}:{vuln_function or 'file-level'}",
            "reachable": is_reachable,
            "confidence": confidence,
            "reason": reason,
            "call_chain": call_chain
        }

    def _get_reachable_files(self) -> Set[str]:
        """Get all files reachable from entry points via BFS."""
        if self._reachable_cache is not None:
            return self._reachable_cache

        reachable = set()
        queue = self.graph.entry_points.copy()

        while queue:
            current_file = queue.pop(0)

            if current_file in reachable:
                continue

            reachable.add(current_file)

            # Add all files this file calls into
            if current_file in self.graph.call_graph:
                for called_file in self.graph.call_graph[current_file]:
                    if called_file not in reachable:
                        queue.append(called_file)

        self._reachable_cache = reachable
        return reachable

    def _find_call_chain(self, target_file: str) -> List[str]:
        """Find shortest call chain from entry point to target file."""
        # BFS to find shortest path
        queue = [(ep, [ep]) for ep in self.graph.entry_points]
        visited = set()

        while queue:
            current_file, path = queue.pop(0)

            if current_file == target_file:
                return path

            if current_file in visited:
                continue

            visited.add(current_file)

            # Explore files called by current file
            if current_file in self.graph.call_graph:
                for called_file in self.graph.call_graph[current_file]:
                    if called_file not in visited:
                        queue.append((called_file, path + [called_file]))

        return []

    def _determine_confidence(self, vuln_file: str, vuln_function: Optional[str],
                             is_reachable: bool) -> str:
        """Determine confidence level of reachability analysis."""
        if not is_reachable:
            # Check if file is imported anywhere
            file_node = self.graph.files.get(vuln_file)
            if file_node:
                # If file has no imports and isn't called, high confidence it's unreachable
                return "HIGH"
            return "MEDIUM"

        # If reachable, check if specific function is called
        if vuln_function:
            # Would need more sophisticated analysis to track function-level reachability
            return "MEDIUM"

        return "HIGH"

    def _generate_reason(self, vuln_file: str, vuln_function: Optional[str],
                        is_reachable: bool, call_chain: List[str]) -> str:
        """Generate human-readable explanation of reachability."""
        if is_reachable:
            if len(call_chain) > 0:
                chain_str = " → ".join(call_chain)
                return f"Reachable via call chain: {chain_str}"
            return "File is reachable from application entry points"
        else:
            file_node = self.graph.files.get(vuln_file)
            if file_node:
                return "Not called from any entry point (dead code or unused module)"
            return "File not found in code graph"


def build_graph_cli(repo_path: str, output_file: str) -> Dict:
    """CLI wrapper for building code graph."""
    builder = PythonCodeGraphBuilder(repo_path)
    graph = builder.build()

    # Convert to serializable format
    graph_dict = {
        "files": {path: asdict(node) for path, node in graph.files.items()},
        "entry_points": graph.entry_points,
        "import_map": graph.import_map,
        "function_map": graph.function_map,
        "call_graph": graph.call_graph,
        "stats": {
            "total_files": len(graph.files),
            "entry_points": len(graph.entry_points),
            "total_functions": sum(len(f.functions) for f in graph.files.values()),
            "total_classes": sum(len(f.classes) for f in graph.files.values())
        }
    }

    # Save to file
    with open(output_file, 'w') as f:
        json.dump(graph_dict, f, indent=2)

    return {
        "status": "success",
        "output_file": output_file,
        "stats": graph_dict["stats"]
    }


def analyze_reachability_cli(graph_file: str, vuln_file: str,
                             vuln_function: Optional[str] = None) -> Dict:
    """CLI wrapper for reachability analysis."""
    # Load graph
    with open(graph_file, 'r') as f:
        graph_dict = json.load(f)

    # Reconstruct CodeGraph
    files = {
        path: FileNode(**node_dict)
        for path, node_dict in graph_dict["files"].items()
    }

    graph = CodeGraph(
        files=files,
        entry_points=graph_dict["entry_points"],
        import_map=graph_dict["import_map"],
        function_map=graph_dict["function_map"],
        call_graph=graph_dict["call_graph"]
    )

    # Analyze reachability
    analyzer = ReachabilityAnalyzer(graph)
    result = analyzer.analyze_vulnerability(vuln_file, vuln_function)

    return {
        "status": "success",
        "analysis": result
    }
