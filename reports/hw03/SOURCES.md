# Sources — HW3 Domain Corpus

Domain: Rental Housing Listings (DOMAIN_ID 6)

| Local filename | Source URL | Access date |
|---|---|---|
| ca_tenants_guide.txt | https://sls.berkeley.edu/wp-content/uploads/2024/05/CA-Tenant-Guide.pdf | 2026-09-18 |
| hud_fair_housing.txt | https://www.hud.gov/sites/documents/doc_10760.pdf | 2026-09-18 |
| sanjose_tpo.txt | https://www.sanjoseca.gov/your-government/departments-offices/housing/housing-rental-rights | 2026-09-18 |
| sanjose_resources.txt | https://www.sanjoseca.gov/your-government/departments-offices/housing/tenants | 2026-09-18 |

## Notes

- `ca_tenants_guide.txt` and `hud_fair_housing.txt` were converted from PDF to plain text using `pdfplumber`.
- `sanjose_tpo.txt` and `sanjose_resources.txt` are San Jose Housing Department pages; their JavaScript-rendered content required a rendering fetch rather than a plain `curl`, since the raw HTML response does not include the actual page text.
- These four sources span three levels of jurisdiction: state (CA DRE), city (San Jose Housing Department), and federal (HUD) — intentionally, so that some San Jose-specific details (e.g., exact relocation benefit amounts, the 13 just-cause eviction reasons) exist in only one source document.
