import plotly.graph_objects as go
import pandas as pd
import sys
import re

# Read CSV file path from command line (required)
if len(sys.argv) < 2:
    print("Usage: python stop-limit-chart-generator.py <csv_file>")
    sys.exit(1)
csv_file = sys.argv[1]

# Read data from CSV
df = pd.read_csv(csv_file)

# Extract Stop and Limit from first formation
stop_price = df.loc[0, 'Stop']
limit_price = df.loc[0, 'Limit']

# Validate Stop and Limit are consistent across all formations
if not all(df['Stop'] == stop_price):
    print(f"ERROR: Stop price is not consistent across all formations")
    sys.exit(1)
if not all(df['Limit'] == limit_price):
    print(f"ERROR: Limit price is not consistent across all formations")
    sys.exit(1)

# Derive title from filename (remove .csv suffix)
import os
title = os.path.basename(csv_file).replace('.csv', '')

# Determine bar type from filename for candle color
bar_type = "bullish" if "bullish" in csv_file.lower() else "bearish"

# Parse fill information to extract fill price
def parse_fill(fill_str):
    """Extract fill price from fill string like 'Stop (100)', 'Open (205)', or 'No fill'"""
    if "No fill" in fill_str:
        return 0
    # Match either "(digits)" or "(word digits)"
    match = re.search(r'\((?:\w+\s+)?(\d+)\)', fill_str)
    return int(match.group(1)) if match else 0

df['fill_price'] = df['Fill'].apply(parse_fill)
df['x'] = df['Formation']

fig = go.Figure()

# Determine candle colors based on bar type
candle_color = "#4CAF50" if bar_type == "bullish" else "#DB4545"

# Add candlestick chart
fig.add_trace(
    go.Candlestick(
        x=df["x"],
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        increasing_line_color=candle_color,
        decreasing_line_color=candle_color,
        increasing_fillcolor=candle_color,
        decreasing_fillcolor=candle_color,
        showlegend=False,
    )
)

# Add Stop line (orange dashed)
fig.add_hline(y=stop_price, line_dash="dash", line_color="orange", line_width=3)

# Add Limit line (brighter green dashed)
fig.add_hline(y=limit_price, line_dash="dash", line_color="#2EFF57", line_width=3)

# Add markers at exact fill prices (single half-transparent marker per formation, only where fill_price > 0)
markers_x = []
markers_y = []
partial_markers_x = []
partial_markers_y = []

for idx, row in df.iterrows():
    if row["fill_price"] > 0:
        # Check if this is a partial fill
        if "Partial fill" in row["Fill"]:
            partial_markers_x.append(row["x"])
            partial_markers_y.append(row["fill_price"])
        else:
            markers_x.append(row["x"])
            markers_y.append(row["fill_price"])

# Add white markers for complete fills
fig.add_trace(
    go.Scatter(
        x=markers_x,
        y=markers_y,
        mode="markers",
        marker=dict(size=20, color="rgba(255, 255, 255, 0.5)", line=dict(width=0)),
        showlegend=False,
        hoverinfo="skip",
    )
)

# Add yellowish markers for partial fills
fig.add_trace(
    go.Scatter(
        x=partial_markers_x,
        y=partial_markers_y,
        mode="markers",
        marker=dict(size=20, color="rgba(255, 215, 0, 0.6)", line=dict(width=0)),  # Yellowish/gold color
        showlegend=False,
        hoverinfo="skip",
    )
)

# Add fill labels dynamically based on fill information
for idx, row in df.iterrows():
    formation = row['Formation']
    fill_str = row['Fill']
    
    # Handle different fill types
    if "No fill" in fill_str:
        fill_text = "No fill"
        # Position above the bar for no-fill cases
        y_pos = row['High'] + 15
    elif "Partial fill" in fill_str:
        # Extract price from partial fill like "Partial fill (Stop 200)"
        fill_text = "Partial fill"
        y_pos = row['Low'] - 15
    elif row['fill_price'] > 0:
        # Extract fill type from Fill column
        fill_type = row['Fill'].split('(')[0].strip()
        fill_text = f"Fill@{fill_type}"
        
        # Position labels based on formation
        if formation in ['F2', 'F3', 'F4', 'F5']:
            y_pos = row['High'] + 15
        elif formation in ['F6', 'F7', 'F8']:
            y_pos = row['Low'] - 15
        else:  # F10, F11
            y_pos = (row['High'] + row['Low']) / 2
    else:
        continue  # Skip if no valid fill information
    
    fig.add_annotation(
        x=formation,
        y=y_pos,
        text=fill_text,
        showarrow=False,
        font=dict(size=18, color="white", family="Arial"),
        bgcolor="rgba(0,0,0,0.5)",
        borderpad=8,
    )

# Add Stop label on Y-axis
fig.add_annotation(
    x=0,
    y=stop_price,
    text=f"Stop {stop_price}",
    showarrow=False,
    xanchor="right",
    xref="paper",
    yref="y",
    font=dict(size=18, color="white", family="Arial"),
    # bgcolor="black",
    # borderpad=6,
)

# Add Limit label on Y-axis
fig.add_annotation(
    x=0,
    y=limit_price,
    text=f"Limit {limit_price}",
    showarrow=False,
    xanchor="right",
    xref="paper",
    yref="y",
    font=dict(size=18, color="white", family="Arial"),
    # bgcolor="black",
    # borderpad=0,
)

# Update layout with clean TradingView style
fig.update_layout(
    title={
        "text": title,
        "x": 0.5,
        "xanchor": "center",
        "font": {
            "size": 26,
            "color": "rgba(224, 224, 224, 0.5)",
            "family": "Arial Black",
        }
    },
    xaxis_title="",
    yaxis_title="",
    xaxis=dict(
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        tickfont=dict(size=18, family="Arial", color="white"),
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        showticklabels=False,
        title="",
    ),
    plot_bgcolor="#131722",
    paper_bgcolor="#131722",
    font=dict(color="white"),
    xaxis_rangeslider_visible=False,
    margin=dict(l=120, r=20, t=80, b=60),
    height=700,
    width=1200,
)

# Show interactive chart
fig.show()
