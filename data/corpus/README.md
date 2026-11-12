# Evaluation corpus

The golden questions and verifier pairs in `data/golden/` and `data/verifier/` are written against these PDFs. The arXiv papers are not committed (they belong to their authors); download them under exactly these names before running `make eval`.

| File | Source |
| :--- | :--- |
| `EarlyStopping_Audit_2611.00166.pdf` | https://arxiv.org/pdf/2611.00166v1 |
| `FlashThink_2505.13949.pdf` | https://arxiv.org/pdf/2505.13949v1 |
| `S-GRPO_2505.07686.pdf` | https://arxiv.org/pdf/2505.07686v2 |
| `Overthinking_o1_2412.21187.pdf` | https://arxiv.org/pdf/2412.21187v2 |
| `Apollo_11_Mission_Report.pdf` | committed; generated sample for the live end-to-end script |

Gold passages are exact spans of the parsed text, so a different version of a paper can break them.
