AI-Driven Home Energy Management System (HEMS)
📌 Overview
This project is a predictive Model Predictive Control (MPC) API designed to optimize residential battery storage against Turkish EPDK three-tier electricity tariffs. By forecasting household energy consumption 120 minutes into the future, the backend dynamically rations battery discharge to maximize financial savings and grid independence during expensive peak hours.

🛠 Tech Stack
Backend Framework: Flask (Python)

Machine Learning: Scikit-learn (Random Forest Regressor), Joblib

Data Processing: Pandas, NumPy, Collections (Deque)

API Interface: RESTful JSON for decoupled Chart.js frontend integration

🧠 Data Engineering & AI Training Phase
Before deployment, a predictive machine learning pipeline was built to understand household consumption habits.

Data Processing: Raw residential usage data (DataSet.csv) was cleaned, normalized, and formatted (cleaned_Data.csv) using Pandas to handle missing values and align time-series indices.

Feature Engineering: To allow the AI to predict the future without complex weather data, we engineered four specific temporal and momentum features:

current_hour: Captures daily routine cycles.

current_day: Captures weekly weekday/weekend behavioral shifts.

lag_1_hour: The exact power demand from 60 minutes prior (momentum).

rolling_3_avg: The moving average of the last 180 minutes (baseline smoothing).

Model Training: A Random Forest Regressor was trained on these features using Scikit-learn to predict the next single minute of power demand.

Serialization: The trained model was frozen and exported via joblib (energy_model.joblib), allowing the Flask backend to perform zero-latency inference without carrying the heavy training datasets into production.

⚙️ Core System Architecture
1. Rolling Horizon Forecasting (predict_future)
Upon receiving a CSV upload of the last 180 minutes of house data, the backend loads the .joblib model. It runs a time-travel loop 120 times, feeding its own predictions back into the rolling_3_avg and lag_1_hour features to successfully forecast a full 2-hour demand array.

2. Model Predictive Controller (decide_battery_dispatch)
Replaces blind heuristic rules with dynamic peak-shaving. Every simulated minute, the controller evaluates the remaining forecasted demand against the real-time battery State of Charge (SoC). If a deficit is detected, the AI calculates a median spike threshold and applies a strict discharge_cap_kw to the inverter, ensuring the battery survives the entire evening.

3. Physical Battery Simulation (VirtualBattery)
Calculates physical power routing while enforcing official 2026 Turkish EPDK pricing:

Night (22:00 - 06:00 | 2.94 TL): Aggressive grid-charging to fill the battery cheaply.

Day (06:00 - 17:00 | 4.38 TL): Battery lock-out. Hoards stored energy for the evening.

Peak (17:00 - 22:00 | 6.17 TL): AI rationing mode. Battery output is governed by the AI's dynamic cap to offset the most expensive grid rates.

📡 API Endpoint Reference
POST /predict
Accepts a multipart CSV upload (csv_file) and returns a structured JSON payload:

chart_data: Arrays of timestamps, AI predictions, battery output (kW), and live SoC (%).

financials: Comparison of Heuristic vs. AI-Optimized costs (TL), Net Savings, and a Grid Independence Score (%).

action_log: Plain-text ledger of the AI's real-time rationing decisions.