import plotly.graph_objects as go
import pandas as pd
import sys
import re
import os

# Read CSV file path from command line (required)
if len(sys.argv) < 2:
    print("Usage: python trailing-stop-chart-generator.py <csv_file>")
    sys.exit(1)
csv_file = sys.argv[1]

# Read data from CSV
df = pd.read_csv(csv_file)

# Strip whitespace from column names
df.columns = df.columns.str.strip()

# Derive title from filename (remove .csv suffix)
title = os.path.basename(csv_file).replace('.csv', '')

# Determine bar type from filename for candle color
bar_type = "bullish" if "bullish" in csv_file.lower() else "bearish"

# Check for TrailingDistance or TrailingPercent columns
has_trailing_distance = 'TrailingDistance' in df.columns
has_trailing_percent = 'TrailingPercent' in df.columns

# Check for carried state (multi-bar scenarios)
has_carry = 'CarriedExtremePrice' in df.columns and 'CarriedStopPrice' in df.columns

# Parse fill information to extract fill price
def parse_fill(fill_str):
    """Extract fill price from fill string like '110.00' or 'No fill'"""
    if pd.isna(fill_str) or "No fill" in str(fill_str).lower() or str(fill_str).strip() == '':
        return None
    # Try to parse as float directly
    try:
        return float(str(fill_str).strip())
    except ValueError:
        return None

# Parse StopFill column if exists
if 'StopFill' in df.columns:
    df['stop_fill_price'] = df['StopFill'].apply(parse_fill)
else:
    df['stop_fill_price'] = None

# Use OrderFill column if it exists, otherwise fall back to Fill
if 'OrderFill' in df.columns:
    fill_column = 'OrderFill'
elif 'Fill' in df.columns:
    fill_column = 'Fill'
else:
    raise ValueError("CSV must contain either 'OrderFill' or 'Fill' column")

df['fill_price'] = df[fill_column].apply(parse_fill)

# Create formation labels with trailing distance/percent based on each row
def create_formation_label(row):
    """Create formation label with trailing info if present."""
    formation = row['Formation']
    
    # Check TrailingDistance first
    if has_trailing_distance and pd.notna(row.get('TrailingDistance')):
        return f"{formation}(Trail{row['TrailingDistance']:.0f}$)"
    # Then check TrailingPercent
    elif has_trailing_percent and pd.notna(row.get('TrailingPercent')):
        return f"{formation}(Trail{row['TrailingPercent']:.1f}%)"
    # No trailing info
    else:
        return formation

df['x'] = df.apply(create_formation_label, axis=1)

# Create numeric index for spreading price paths
df['x_numeric'] = range(len(df))

fig = go.Figure()

# Add candlestick chart first (with legend)
# Bullish (close > open) = green, Bearish (close < open) = red
fig.add_trace(
    go.Candlestick(
        x=df["x_numeric"],
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        increasing_line_color="#4CAF50",  # Green for bullish candles
        decreasing_line_color="#DB4545",  # Red for bearish candles
        increasing_fillcolor="#4CAF50",
        decreasing_fillcolor="#DB4545",
        name="Candles",
        showlegend=True,
        legendgroup="candles",
    )
)

# Add price movement path lines for each candle (with legend control)
for idx, row in df.iterrows():
    is_bullish = row['Close'] > row['Open']
    has_carried = pd.notna(row.get('CarriedExtremePrice'))
    
    # Build price path
    if has_carried:
        if is_bullish:
            # Carried → Open → Low → High → Close
            y_path = [row['CarriedExtremePrice'], row['Open'], row['Low'], row['High'], row['Close']]
        else:
            # Carried → Open → High → Low → Close
            y_path = [row['CarriedExtremePrice'], row['Open'], row['High'], row['Low'], row['Close']]
    else:
        if is_bullish:
            # Open → Low → High → Close
            y_path = [row['Open'], row['Low'], row['High'], row['Close']]
        else:
            # Open → High → Low → Close
            y_path = [row['Open'], row['High'], row['Low'], row['Close']]
    
    # Create x-coordinates spreading horizontally within candle area
    num_points = len(y_path)
    x_center = row['x_numeric']
    # Spread points from -0.3 to +0.3 (relative to candle width)
    if num_points > 1:
        x_path = [x_center + (i / (num_points - 1) - 0.5) * 1 for i in range(num_points)]
    else:
        x_path = [x_center]
    
    # Add the path line with spline smoothing
    fig.add_trace(
        go.Scatter(
            x=x_path,
            y=y_path,
            mode='lines+markers',
            line=dict(
                color='rgba(173, 216, 230, 0.7)',  # Light blue
                width=1,
                shape='spline',  # Rounded/smooth lines
                smoothing=1.3
            ),
            marker=dict(
                size=6,
                color='rgba(173, 216, 230, 0.9)',
                symbol='circle'
            ),
            name='Price Path' if idx == 0 else '',
            showlegend=True if idx == 0 else False,
            legendgroup='paths',
            hoverinfo='text',
            text=[f"{row['x']}<br>Price: {y:.2f}" for y in y_path],
        )
    )

# Add horizontal lines for extreme prices and stop prices (if they vary by formation)
# For single-bar scenarios, extremePrice and currentStopPrice should be consistent
if 'extremePrice' in df.columns:
    extreme_prices = df['extremePrice'].dropna().unique()
    for extreme in extreme_prices:
        fig.add_hline(
            y=extreme, 
            line_dash="dot", 
            line_color="rgba(100, 149, 237, 0.5)",  # Cornflower blue, semi-transparent
            line_width=2,
            annotation_text=f"Extreme {extreme:.2f}",
            annotation_position="left",
            annotation_font=dict(size=14, color="rgba(100, 149, 237, 0.8)", family="Arial")
        )

if 'currentStopPrice' in df.columns:
    stop_prices = df['currentStopPrice'].dropna().unique()
    for stop in stop_prices:
        fig.add_hline(
            y=stop, 
            line_dash="dash", 
            line_color="orange", 
            line_width=3,
            annotation_text=f"Stop {stop:.2f}",
            annotation_position="left",
            annotation_font=dict(size=16, color="orange", family="Arial")
        )

# Add markers for carried state (if exists)
if has_carry:
    for idx, row in df.iterrows():
        if pd.notna(row.get('CarriedExtremePrice')):
            fig.add_hline(
                y=row['CarriedExtremePrice'],
                line_dash="dot",
                line_color="rgba(255, 165, 0, 0.3)",  # Orange, very transparent
                line_width=1
            )
        if pd.notna(row.get('CarriedStopPrice')):
            fig.add_hline(
                y=row['CarriedStopPrice'],
                line_dash="dashdot",
                line_color="rgba(255, 69, 0, 0.4)",  # Red-orange, semi-transparent
                line_width=2
            )

# Add fill markers
stop_fill_markers_x = []
stop_fill_markers_y = []
order_fill_markers_x = []
order_fill_markers_y = []
carried_extreme_x = []
carried_extreme_y = []

for idx, row in df.iterrows():
    # Add stop fill markers (square yellow)
    if row["stop_fill_price"] is not None:
        stop_fill_markers_x.append(row["x_numeric"])
        stop_fill_markers_y.append(row["stop_fill_price"])
    
    # Add order fill markers (round white)
    if row["fill_price"] is not None:
        order_fill_markers_x.append(row["x_numeric"])
        order_fill_markers_y.append(row["fill_price"])
    
    # Add carried extreme price markers
    # if pd.notna(row.get('CarriedExtremePrice')):
    #     carried_extreme_x.append(row["x_numeric"])
    #     carried_extreme_y.append(row['CarriedExtremePrice'])

# Add yellow square markers for stop fills (behind)
if stop_fill_markers_x:
    fig.add_trace(
        go.Scatter(
            x=stop_fill_markers_x,
            y=stop_fill_markers_y,
            mode="markers",
            marker=dict(
                size=20, 
                color="rgba(255, 215, 0, 0.6)",  # Yellow/gold color
                symbol="square",
                line=dict(width=0)
            ),
            showlegend=False,
            hoverinfo="skip",
        )
    )

# Add white circular markers for order fills (in front)
if order_fill_markers_x:
    fig.add_trace(
        go.Scatter(
            x=order_fill_markers_x,
            y=order_fill_markers_y,
            mode="markers",
            marker=dict(
                size=20, 
                color="rgba(255, 255, 255, 0.5)",  # White color
                symbol="circle",
                line=dict(width=2, color="rgba(255, 255, 255, 0.8)")
            ),
            showlegend=False,
            hoverinfo="skip",
        )
    )

# Add carried extreme price markers (blue diamond)
if carried_extreme_x:
    fig.add_trace(
        go.Scatter(
            x=carried_extreme_x,
            y=carried_extreme_y,
            mode="markers",
            marker=dict(
                size=16, 
                color="rgba(100, 149, 237, 0.8)",  # Cornflower blue
                symbol="diamond",
                line=dict(width=2, color="rgba(100, 149, 237, 1)")
            ),
            showlegend=False,
            hoverinfo="text",
            text=[f"Carried: {y:.2f}" for y in carried_extreme_y],
        )
    )

# Add fill labels
for idx, row in df.iterrows():
    formation = row['Formation']
    
    # Use OrderFill column if it exists, otherwise fall back to Fill
    fill_column = 'OrderFill' if 'OrderFill' in df.columns else 'Fill'
    fill_value = row[fill_column]
    
    # Determine if filled
    filled = row['fill_price'] is not None and not pd.isna(row['fill_price'])
    
    # Position labels
    if filled:
        y_pos = row['Low'] - 5 # Below bar for fills
        fill_text = f"Fill@{row['fill_price']:.2f}"
    else:
        y_pos = row['Low'] - 5  # Above bar for no fills
        fill_text = "No fill"
    
    fig.add_annotation(
        x=row['x_numeric'],
        y=y_pos,
        text=fill_text,
        showarrow=False,
        font=dict(size=10, color="white", family="Arial"),
        bgcolor="rgba(0,0,0,0.5)",
        borderpad=8,
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
        tickmode='array',
        tickvals=df['x_numeric'].tolist(),
        ticktext=df['x'].tolist(),
        zeroline=False,
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        showticklabels=True,
        tickfont=dict(size=18, family="Arial", color="white"),
        title="",
        zeroline=False,
        zerolinewidth=0,
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
