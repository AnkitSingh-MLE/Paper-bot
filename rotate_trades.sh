#!/bin/bash
DATE=$(date +%Y-%m-%d)

# Updated to your actual home directory
PROJECT_DIR="/home/shruti_gupta015/"
TRADES_FILE="${PROJECT_DIR}trades.csv"
ARCHIVE_FILE="${PROJECT_DIR}trades_archived_$DATE.csv"

if [ -f "$TRADES_FILE" ]; then
    mv "$TRADES_FILE" "$ARCHIVE_FILE"
    echo "SUCCESS: Archived to $ARCHIVE_FILE"
    
    HEADERS="timestamp,date,symbol,strategy,timeframe,direction,entry,target,stop,qty,rrr,score,notes,pattern,pattern_pts,near_support,support_val,support10_val,support_pts,vol_surge,vol_ratio,vol_pts,ema_aligned,ema_20_val,ema_50_val,ema_200_val,ema_pts,rsi_fired,rsi_val,rsi_pts,macd_fired,macd_hist,macd_pts,adx_fired,adx_val,adx_pts,vwap_val,atr,result,pnl"
    echo "$HEADERS" > "$TRADES_FILE"
    echo "New trades.csv created with correct schema."
else
    echo "ERROR: trades.csv not found at $TRADES_FILE."
fi
