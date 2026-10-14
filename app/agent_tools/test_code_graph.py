#!/usr/bin/env python3
"""Test script for code_graph module - validates reachability analysis works correctly."""

import json
import tempfile
import shutil
from pathlib import Path
from code_graph import PythonCodeGraphBuilder, ReachabilityAnalyzer


def create_test_repo():
    """Create a minimal test repository structure."""
    test_dir = Path(tempfile.mkdtemp())

    # Create main.py (entry point)
    (test_dir / "main.py").write_text("""
import app

if __name__ == "__main__":
    app.run()
""")

    # Create app.py (reachable from main)
    (test_dir / "app.py").write_text("""
from database import query_user

def run():
    user = query_user(1)
    print(user)
""")

    # Create database.py (reachable from app)
    (test_dir / "database.py").write_text("""
def query_user(user_id):
    # VULNERABLE: SQL injection
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query

def legacy_function():
    # UNREACHABLE: Never called
    pass
""")

    # Create utils.py (NOT reachable - not imported)
    (test_dir / "utils.py").write_text("""
def unused_helper():
    # UNREACHABLE: Module never imported
    pass
""")

    return test_dir


def test_code_graph_builder():
    """Test that code graph builder correctly identifies structure."""
    print("Testing code graph builder...")

    test_dir = create_test_repo()

    try:
        builder = PythonCodeGraphBuilder(str(test_dir))
        graph = builder.build()

        # Verify entry points
        assert len(graph.entry_points) == 1, f"Expected 1 entry point, got {len(graph.entry_points)}"
        assert "main.py" in graph.entry_points, "main.py should be entry point"

        # Verify files analyzed
        assert len(graph.files) == 4, f"Expected 4 files, got {len(graph.files)}"

        # Verify imports detected
        assert "app" in graph.files["main.py"].imports, "main.py should import app"
        assert "database" in graph.files["app.py"].imports, "app.py should import database"

        # Verify functions detected
        assert "run" in graph.files["app.py"].functions, "app.py should define run()"
        assert "query_user" in graph.files["database.py"].functions
        assert "legacy_function" in graph.files["database.py"].functions

        print("✅ Code graph builder: PASSED")
        return graph, test_dir

    except AssertionError as e:
        print(f"❌ Code graph builder: FAILED - {e}")
        shutil.rmtree(test_dir)
        return None, None


def test_reachability_analyzer(graph, test_dir):
    """Test that reachability analyzer correctly identifies reachable code."""
    print("\nTesting reachability analyzer...")

    if not graph:
        print("❌ Skipping reachability tests (graph builder failed)")
        return

    try:
        analyzer = ReachabilityAnalyzer(graph)

        # Test 1: main.py should be reachable (it's an entry point)
        result = analyzer.analyze_vulnerability("main.py")
        assert result["reachable"] == True, "main.py should be reachable (entry point)"
        print("  ✓ Entry point correctly identified as reachable")

        # Test 2: app.py should be reachable (imported by main)
        result = analyzer.analyze_vulnerability("app.py")
        assert result["reachable"] == True, "app.py should be reachable"
        assert len(result["call_chain"]) > 0, "Should have call chain"
        print(f"  ✓ app.py reachable via: {' → '.join(result['call_chain'])}")

        # Test 3: database.py should be reachable (imported by app)
        result = analyzer.analyze_vulnerability("database.py")
        assert result["reachable"] == True, "database.py should be reachable"
        assert "main.py" in result["call_chain"], "Call chain should include main.py"
        print(f"  ✓ database.py reachable via: {' → '.join(result['call_chain'])}")

        # Test 4: utils.py should NOT be reachable (never imported)
        result = analyzer.analyze_vulnerability("utils.py")
        assert result["reachable"] == False, "utils.py should NOT be reachable"
        assert len(result["call_chain"]) == 0, "Should have empty call chain"
        print(f"  ✓ utils.py correctly identified as unreachable: {result['reason']}")

        print("✅ Reachability analyzer: PASSED")

    except AssertionError as e:
        print(f"❌ Reachability analyzer: FAILED - {e}")
    finally:
        shutil.rmtree(test_dir)


def test_statistics():
    """Test that statistics are correctly computed."""
    print("\nTesting statistics computation...")

    test_dir = create_test_repo()

    try:
        builder = PythonCodeGraphBuilder(str(test_dir))
        graph = builder.build()

        stats = {
            "total_files": len(graph.files),
            "entry_points": len(graph.entry_points),
            "total_functions": sum(len(f.functions) for f in graph.files.values()),
        }

        assert stats["total_files"] == 4, f"Expected 4 files, got {stats['total_files']}"
        assert stats["entry_points"] == 1, f"Expected 1 entry point, got {stats['entry_points']}"
        assert stats["total_functions"] >= 4, f"Expected at least 4 functions, got {stats['total_functions']}"

        print(f"  ✓ Statistics: {json.dumps(stats, indent=2)}")
        print("✅ Statistics computation: PASSED")

    except AssertionError as e:
        print(f"❌ Statistics computation: FAILED - {e}")
    finally:
        shutil.rmtree(test_dir)


def main():
    """Run all tests."""
    print("=" * 60)
    print("SOVA Reachability Analysis - Test Suite")
    print("=" * 60)

    # Test 1: Code graph builder
    graph, test_dir = test_code_graph_builder()

    # Test 2: Reachability analyzer
    if graph:
        test_reachability_analyzer(graph, test_dir)

    # Test 3: Statistics
    test_statistics()

    print("\n" + "=" * 60)
    print("Test Suite Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
