# Source Access Evidence

Milestone 2 allows bounded public HTTP discovery for only these observed sources:

- VietnamWorks observed endpoint: `POST https://ms.vietnamworks.com/job-search/v1.0/search`
- ITviec observed search URL: `https://itviec.com/it-jobs/c-plus-plus/ha-noi`

No credentials, cookies, browser automation, CAPTCHA/WAF bypass, application submissions, invented endpoints, invented location IDs, or fabricated request payloads are used.

Live status is recorded in [milestone-2-live-benchmark.json](benchmarks/milestone-2-live-benchmark.json). If policy discovery is blocked or unverified, live extraction is skipped or reported as zero extraction. Offline fixture adapters remain functional and are clearly separated from live evidence.
