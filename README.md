# Converged Networks — research code

A code-only repository for Converged Networks experiments, including bursty traffic simulations, CellReplay queue-accounting checks, native C++/ns-3 fixtures, audit scripts, test cases and frozen experimental configurations.

**Scope:** This repository is for source code and reproducibility materials. The IEEE paper, slides, LaTeX manuscript files and the large original raw-data archive are intentionally excluded.

**Upload status:** This README initializes the repository. The full source tree has been prepared and tested (194 Python unit tests passed locally), but still needs to be pushed from the code-only upload package. After upload, the source-tree README replaces this placeholder.

The original 20 ms deadline was not met in the reported trials. The 40 ms results are sensitivity checks, and reuse of wireless-service traces limits independent-sample claims.

Run tests after the source files have been pushed:

```bash
python -m unittest discover -s tests -q
```
