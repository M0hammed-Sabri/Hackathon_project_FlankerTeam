import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request
from collections import deque



app= Flask(__name__)


class VirtualBattery:
    def __init__(self, max_capacity_kwh=10.0, max_output_kw=5.0):
        self.max_capacity_kwh = max_capacity_kwh
        self.current_charge_kwh = 0.0
        self.max_output_kw = max_output_kw
        
        # Prices 2026 April
        self.price_nigth = 2.94   # 22:00 - 06:00
        self.price_day = 4.38 # 06:00 - 17:00
        self.price_evening = 6.17  # 17:00 - 22:00
        self.price_export = 3.50 # Net metering credit rate

    def calculate_power_flow(self, hour, demand_kw, solar_kw, discharge_cap_kw):
        grid_draw_kw = 0.0
        battery_output_kw = 0.0
        exported_solar_kw = 0.0
        
        # Night shift(Cheap Grid Charging)
        if hour >= 22 or hour < 6:
            charge_needed = self.max_capacity_kwh - self.current_charge_kwh
            charge_amount = min(charge_needed, self.max_output_kw)
            self.current_charge_kwh += charge_amount
            grid_draw_kw = demand_kw + charge_amount
            current_price = self.price_nigth

        #Solar energy (Daytime)
        elif 6 <= hour < 17:
            current_price = self.price_day
            if solar_kw > demand_kw:
                excess_solar = solar_kw - demand_kw
                space_left = self.max_capacity_kwh - self.current_charge_kwh
                charge_amount = min(excess_solar, space_left)
                self.current_charge_kwh += charge_amount
                exported_solar_kw = excess_solar - charge_amount
            else:
                grid_draw_kw = demand_kw - solar_kw

        # Peak Price (expensive evening - AI active)
        elif 17 <= hour < 22:
            current_price = self.price_evening
            remaining_demand = max(0, demand_kw - solar_kw)
            
            if solar_kw > demand_kw:
                excess_solar = solar_kw - demand_kw
                space_left = self.max_capacity_kwh - self.current_charge_kwh
                charge_amount = min(excess_solar, space_left)
                self.current_charge_kwh += charge_amount
                exported_solar_kw = excess_solar - charge_amount
 
            #Battery output is limited by the discharge cap
            battery_output_kw = min(remaining_demand, discharge_cap_kw, self.current_charge_kwh)
            self.current_charge_kwh -= battery_output_kw
            grid_draw_kw = remaining_demand - battery_output_kw

        # Financial Math (Divided by 60 because we run minute-by-minute)
        cost = ((grid_draw_kw * current_price) - (exported_solar_kw * self.price_export)) / 60
        
        #what it would cost with NO battery (for comparing)
        no_AI_cost = ((max(0, demand_kw - solar_kw) * current_price) - (max(0, solar_kw - demand_kw) * self.price_export)) / 60

        return {
            "grid_draw_kw": grid_draw_kw,
            "battery_output_kw": battery_output_kw,
            "ai_cost_TL": cost,
            "no_AI_cost_TL": no_AI_cost
        }


    
model = joblib.load('Model/energy_model.joblib')


def predict_future(initial_180_minutes, steps_to_predict=120, start_hour=17, start_day=1):
    """
    initial_180_minutes:  last 180 power readings
    steps_to_predict: How many minutes into the future we want predict
    """


    #stores the past 180 meniutes as a queue so we can push the oldest ones and replace them with our model's predections 
    memory = deque(initial_180_minutes, maxlen=180)

    future_predictions = []
    
    current_hour = start_hour
    current_day = start_day

    # 3. The Time-Travel Loop
    for step in range(steps_to_predict):
        
        # the clues : 3 hour avg // exactly 1 hour earlier consumption
        rolling_3_avg = sum(memory) / 180
        lag_1_hour = memory[120]  
        
        features = np.array([[current_hour, current_day, lag_1_hour, rolling_3_avg]])
        
        #Predict and save the next minute
        next_minute_power = float(model.predict(features)[0])
        future_predictions.append(next_minute_power)
        
        
        memory.append(next_minute_power)
        
        #clock updating
        if (step + 1) % 60 == 0:
            current_hour = (current_hour + 1) % 24
            if current_hour == 0:
                current_day = (current_day + 1) % 7
                
    return future_predictions



def decide_battery_dispatch(predicted_demand_120, current_battery_kwh, max_output_kw):
    # How much energy will the house need in 2 hours 
    forecasted_energy_kwh = sum(predicted_demand_120) / 60.0
    
    # is battery able to cover?
    if forecasted_energy_kwh <= current_battery_kwh:
        discharge_cap_kw = max_output_kw #keep using battery
    else:
        # we find the median demand; The battery will only help with usage above this number.
        median_spike_threshold = float(np.median(predicted_demand_120))
        
        discharge_cap_kw = min(median_spike_threshold, max_output_kw)# saftey check for the inverter

    return discharge_cap_kw



@app.route('/')
def home():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
def get_prediction():
    file = request.files['csv_file']
    df = pd.read_csv(file)
    
    #last 180 minutes of data (iloc[:, 0] => the coulmn on index 0 regardless the name)
    real_past_data = df.iloc[:, 0].tail(180).tolist()
    
    #Run the AI to get the 120-minute forecast array
    predicted_forecast_120 = predict_future(real_past_data, steps_to_predict=120)
    
    #create the battery 
    home_battery = VirtualBattery(max_capacity_kwh=10.0, max_output_kw=5.0)


    
    ui_timestamps = [] #use this for the time lap as an x axis
    #use these 2 for comparing
    ui_predicted_kw = [] 
    ui_battery_output = []
    
    total_ai_cost = 0.0
    total_no_AI_cost = 0.0
    action_logs = [] #tell the user what the ai did

    current_hour = 17 # Assuming simulation starts at 17:00 for the peak window
    current_minute = 0
    
    #Calculate the AI strategy based on the forecast
    discharge_cap = decide_battery_dispatch(predicted_forecast_120, home_battery.current_charge_kwh, home_battery.max_output_kw)
    action_logs.append(f"AI Strategy: Battery discharge capped at {discharge_cap:.2f} kW to survive peak hours.")



    ui_battery_percent = [] # Tracks the State of Charge (0% to 100%)
    minutes_off_grid = 0 # Tracks our new Grid Independence Score

    for i, predicted_kw in enumerate(predicted_forecast_120):


        remaining_forecast = predicted_forecast_120[i:]
        
        discharge_cap = decide_battery_dispatch(
            predicted_demand_120=remaining_forecast, 
            current_battery_kwh=home_battery.current_charge_kwh, 
            max_output_kw=home_battery.max_output_kw
        )

        #battery is used meansthere is no solar energy (phase3) 
        solar_kw = 0.0 
        
        power_flow = home_battery.calculate_power_flow(
            hour=current_hour, 
            demand_kw=predicted_kw, 
            solar_kw=solar_kw, 
            discharge_cap_kw=discharge_cap
        )

        # Calculate Battery percentage
        battery_percent = (home_battery.current_charge_kwh / home_battery.max_capacity_kwh) * 100
        ui_battery_percent.append(round(battery_percent, 1))

        if power_flow["grid_draw_kw"] == 0:
            minutes_off_grid += 1

        total_ai_cost += power_flow["ai_cost_TL"]
        total_no_AI_cost += power_flow["no_AI_cost_TL"]
        
        timestamp_str = f"{int(current_hour):02d}:{int(current_minute):02d}"
        
        #for the UI chart
        ui_timestamps.append(timestamp_str)
        ui_predicted_kw.append(round(predicted_kw, 2))
        ui_battery_output.append(round(power_flow["battery_output_kw"], 2))
        
        current_minute += 1
        if current_minute == 60:
            current_minute = 0
            current_hour = (current_hour + 1) % 24

    return jsonify({
        "chart_data": {
            "timestamps": ui_timestamps,
            "predicted_demand_kw": ui_predicted_kw,
            "battery_output_kw": ui_battery_output,
            "battery_percent": ui_battery_percent  
        },
        "financials": {
            "no_AI_cost_tl": round(total_no_AI_cost, 2),
            "ai_optimized_cost_tl": round(total_ai_cost, 2),
            "total_savings_tl": round(total_no_AI_cost - total_ai_cost, 2),
            "grid_independence_score": round((minutes_off_grid / 120) * 100, 1) 
        },
        "action_log": action_logs
    })

app.run(debug=True)