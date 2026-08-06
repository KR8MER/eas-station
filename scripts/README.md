# EAS Station™ Utility Scripts

## Quick Reference

| Script | Purpose | Command |
|--------|---------|---------|
| `collect_sdr_diagnostics.sh` | Collect SDR diagnostic logs | `bash scripts/collect_sdr_diagnostics.sh` |
| `sdr_diagnostics.py` | Quick SDR device check | `python3 scripts/sdr_diagnostics.py` |
| `diagnose_502_504.sh` | Diagnose 502/504 gateway errors | `sudo bash scripts/diagnose_502_504.sh` |
| `diagnose_startup.sh` | Service startup diagnostics | `sudo bash scripts/diagnose_startup.sh` |
| `fix_git.sh` | Restore missing .git directory | `sudo bash scripts/fix_git.sh` |
| `fix_admin_roles.py` | Fix admin role assignments | `python3 scripts/fix_admin_roles.py` |
| `merge_env.py` | Add missing .env variables | `python3 scripts/merge_env.py --backup` |
| `check_dependencies.py` | Verify Python dependencies | `python3 scripts/check_dependencies.py` |
| `validate_imports.py` | Check all imports load correctly | `python3 scripts/validate_imports.py` |
| `zone_derive_helper.py` | Derive FIPS/SAME zone codes | `python3 scripts/zone_derive_helper.py` |
| `fips_lookup_helper.py` | Look up FIPS county codes | `python3 scripts/fips_lookup_helper.py` |
| `setup_smart_monitoring.sh` | Configure S.M.A.R.T. disk monitoring | `sudo bash scripts/setup_smart_monitoring.sh` |
| `setup_postal.sh` | Set up Postfix local mail relay | `sudo bash scripts/setup_postal.sh` |
| `restart_services.sh` | Restart all EAS Station™ services | `sudo bash scripts/restart_services.sh` |
| `warmup_workers.sh` | Pre-warm Gunicorn workers | `bash scripts/warmup_workers.sh` |
| `configure.py` | Interactive first-run configuration | `python3 scripts/configure.py` |

## SDR Troubleshooting

```bash
# Comprehensive diagnostic log collection
bash scripts/collect_sdr_diagnostics.sh

# Quick SDR device check
python3 scripts/sdr_diagnostics.py

# Test SDR capture at a specific frequency
python3 scripts/sdr_diagnostics.py --test-capture --frequency 162550000
```

## Database Utilities

Scripts for database maintenance are in `scripts/database/`.

## Diagnostics

Scripts for service and system diagnostics are in `scripts/diagnostics/`.

## Debug Tools

Advanced debug utilities are in `scripts/debug/` — intended for developers diagnosing specific subsystems.
