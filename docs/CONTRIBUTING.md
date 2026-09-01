# Contributing to HADIN-COMBAT

Thanks for helping build the AI opponent that learns your fighting DNA! 🥋

---

## Getting Started

1. Fork the repository and clone it.
2. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature
   ```
3. Set up the dev environment:
   ```bash
   bash scripts/setup_dev.sh
   ```

---

## Code Style

### C++ (C++17)
- Follow [Google C++ Style](https://google.github.io/styleguide/cppguide.html)
  with 4-space indentation.
- Keep all public API in `namespace hadin`.
- Use `std::optional` for fallible inference calls; never throw across the
  Python boundary.
- Every file starts with the HADIN-COMBAT copyright header.

### Python (3.10+)
- Type hints on all public functions.
- `snake_case` for functions/variables, `PascalCase` for classes.
- Run a linter before submitting:
  ```bash
  pip install ruff black
  ruff check python-backend && black --check python-backend
  ```

### JavaScript
- `camelCase`, `'use strict'`, no external dependencies in the core app.
- Keep the frontend **zero-install** and **mobile-first**.

### HTML/CSS
- Semantic markup, dark theme with neon accents, thumb-friendly controls.

---

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(pose): add ONNX pose inference
fix(ws): reconnect after socket close
docs(api): document frame message schema
refactor(cpp): simplify opponent generator
test(backend): cover mediapipe fallback
```

Prefixes: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `ci`,
`build`, `chore`.

---

## Pull Request Process

1. Keep changes focused and atomic.
2. Add/update tests for backend changes:
   ```bash
   cd python-backend && pytest tests/
   ```
3. Update documentation if you change public APIs or messages.
4. Ensure CI passes (C++ build, Python tests, JS lint).
5. Request review and address feedback.

---

## Testing

- **Backend:** `python-backend/tests/` — pytest suite (pose, processor,
  fallback logic).
- **C++:** build with `-DCMAKE_BUILD_TYPE=Debug` and run unit checks.
- **Frontend:** manual testing across Chrome/Safari mobile + desktop.

Run the full check:
```bash
# in CI order
cmake -S cpp -B build && cmake --build build
cd python-backend && pytest
node scripts/lint-js.js
```

---

## Reporting Issues

Open an issue with:
- A clear, minimal title.
- Steps to reproduce.
- Expected vs actual behaviour.
- Device/OS/browser and backend (`cpp` or `mediapipe`).

---

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](../LICENSE) (c) 2026 Al-hassan Shehade & Dina Balcheh.
