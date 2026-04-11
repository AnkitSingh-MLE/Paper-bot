#!/bin/bash
cd /home/shruti_gupta015/paper-bot
git add trades.csv trades_archived_*.csv
git commit -m "auto: weekly trades sync $(date +%Y-%m-%d)" 2>/dev/null || echo "nothing to commit"
git push
