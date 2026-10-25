## Integration test: find the file that contains DEBUG

**write_file app.py**
```
{
  "success": true,
  "data": {
    "path": "app.py",
    "bytes": 25,
    "created": true
  }
}
```

**write_file helpers.py**
```
{
  "success": true,
  "data": {
    "path": "helpers.py",
    "bytes": 34,
    "created": true
  }
}
```

**write_file config.py**
```
{
  "success": true,
  "data": {
    "path": "config.py",
    "bytes": 14,
    "created": true
  }
}
```

**glob_files "**/*.py"**
```
{
  "success": true,
  "data": {
    "files": [
      "app.py",
      "config.py",
      "helpers.py"
    ],
    "count": 3,
    "truncated": false
  }
}
```

**search_in_files "DEBUG" in *.py**
```
{
  "success": true,
  "data": {
    "matches": [
      {
        "file": "helpers.py",
        "line": 2,
        "text": "    print('DEBUG', x)"
      }
    ],
    "count": 1,
    "truncated": false
  }
}
```

**read_file helpers.py**
```
{
  "success": true,
  "data": {
    "path": "helpers.py",
    "lines": [
      "1: def log(x):",
      "2:     print('DEBUG', x)"
    ],
    "total_lines": 2,
    "truncated": false
  }
}
```

**edit_file helpers.py (remove the debug print)**
```
{
  "success": true,
  "data": {
    "path": "helpers.py",
    "diff": "--- a/helpers.py\n+++ b/helpers.py\n@@ -1,2 +1,2 @@\n def log(x):\n-    print('DEBUG', x)\n+    pass",
    "diff_truncated": false
  }
}
```

Result: the file containing DEBUG is **helpers.py**.