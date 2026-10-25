## Safety-gate test (10 commands)

| # | Command | Expected | Gate (auto_approve=False) | Gate (auto_approve=True) | Reason |
|---|---|---|---|---|---|
| 1 | `ls -la` | allow | allow | allow | safe prefix |
| 2 | `cat notes.txt` | allow | allow | allow | safe prefix |
| 3 | `python -m pytest -q` | allow | allow | allow | safe prefix |
| 4 | `rm -rf build` | block | block | block | destructive (recursive deletion): needs an explicit yes from the user; auto_approve does not apply |
| 5 | `ls && rm -rf /` | block | block | block | destructive (recursive deletion): needs an explicit yes from the user; auto_approve does not apply |
| 6 | `sudo ls` | block | block | block | destructive (privilege escalation): needs an explicit yes from the user; auto_approve does not apply |
| 7 | `chmod -R 777 .` | block | block | block | destructive (permission or ownership change): needs an explicit yes from the user; auto_approve does not apply |
| 8 | `dd if=/dev/zero of=/dev/disk2` | block | block | block | destructive (raw device write): needs an explicit yes from the user; auto_approve does not apply |
| 9 | `mkfs.ext4 /dev/sdb1` | block | block | block | destructive (filesystem creation): needs an explicit yes from the user; auto_approve does not apply |
| 10 | `echo x > /etc/hosts` | block | block | block | destructive (redirection to a root path): needs an explicit yes from the user; auto_approve does not apply |

10/10 commands behaved as expected.
`bash('rm -rf build', auto_approve=True)` -> success=False, error='blocked: destructive (recursive deletion): needs an explicit yes from the user; auto_approve does not apply'; canary file still exists: True.