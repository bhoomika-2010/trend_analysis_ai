import pandas as pd
import numpy as np
import warnings
import os
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
warnings.filterwarnings("ignore")

def create_sequences(data, sequence_length):
    """
    Creates time-series sequences from the data.
    """
    X, y = [], []
    for i in range(len(data) - sequence_length):
        X.append(data[i:(i + sequence_length)])
        y.append(data[i + sequence_length])
    return np.array(X), np.array(y)

def generate_forecast(historical_data):
    """
    Takes historical trend data (daily OR weekly), auto-detects the frequency,
    trains a TensorFlow/Keras LSTM model, and returns a forecast.
    """
    
    # 1. --- Data Preparation ---
    if not historical_data or len(historical_data) < 30: # Need at least 30 data points
        print("FORECASTING_WARNING: Not enough historical data for a reliable TensorFlow forecast.")
        return None

    try:
        df = pd.DataFrame(historical_data)
        df['date'] = pd.to_datetime(df['date'])

        if df.duplicated(subset=['date']).any():
            print("DUPLICATE_DATES_FOUND: Consolidating duplicate date entries.")
            df = df.groupby('date')['score'].mean().reset_index()
            
        df.set_index('date', inplace=True)
        
        # --- NEW: Auto-detect Frequency ---
        # Get the time difference between the first two data points
        time_diff = (df.index[1] - df.index[0]).days
        
        if time_diff < 3:
            # --- DAILY DATA ---
            print("Data appears to be DAILY. Using daily model.")
            FREQ = 'D'
            SEQUENCE_LENGTH = 30 # Look back 30 days
            FORECAST_STEPS = 90  # Forecast 90 days
            FORECAST_FREQ = 'D'
        else:
            # --- WEEKLY DATA ---
            print("Data appears to be WEEKLY. Using weekly model.")
            FREQ = 'W'
            SEQUENCE_LENGTH = 12 # Look back 12 weeks
            FORECAST_STEPS = 12  # Forecast 12 weeks
            FORECAST_FREQ = 'W'
        # --- END NEW ---

        # Resample based on the detected frequency
        df = df.resample(FREQ).mean()
        df['score'].interpolate(method='time', inplace=True)
        
        # 2. --- Data Scaling ---
        scaler = MinMaxScaler(feature_range=(0, 1))
        scaled_data = scaler.fit_transform(df[['score']])

        # 3. --- Create Sequences ---
        if len(scaled_data) < SEQUENCE_LENGTH + 1:
             print(f"FORECASTING_WARNING: Not enough {FREQ} data points to create a sequence.")
             return None

        X, y = create_sequences(scaled_data, SEQUENCE_LENGTH)
        X = X.reshape(X.shape[0], X.shape[1], 1)

        # 4. --- Build & Train the LSTM Model ---
        print(f"--- Building and training TensorFlow LSTM model ({FREQ})... ---")
        model = Sequential()
        model.add(LSTM(50, return_sequences=True, input_shape=(SEQUENCE_LENGTH, 1)))
        model.add(LSTM(50, return_sequences=False))
        model.add(Dense(25))
        model.add(Dense(1))

        model.compile(optimizer='adam', loss='mean_squared_error')
        
        # Use a larger batch_size for faster training
        model.fit(X, y, batch_size=16, epochs=5, verbose=0)
        print("✅ TensorFlow model training complete.")

        # 5. --- Generate Forecast ---
        forecast_input = scaled_data[-SEQUENCE_LENGTH:].tolist()
        forecast_scaled = []

        for _ in range(FORECAST_STEPS):
            current_input = np.array(forecast_input[-SEQUENCE_LENGTH:])
            current_input = current_input.reshape((1, SEQUENCE_LENGTH, 1))
            
            predicted_value = model.predict(current_input, verbose=0)[0][0]
            
            forecast_scaled.append(predicted_value)
            forecast_input.append([predicted_value])

        # 6. --- Inverse Scale & Format ---
        forecast_values = scaler.inverse_transform(np.array(forecast_scaled).reshape(-1, 1))
        
        last_date = df.index[-1]
        
        # Create a new date range based on the detected frequency
        if FREQ == 'D':
            forecast_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=FORECAST_STEPS, freq='D')
        else:
            forecast_dates = pd.date_range(start=last_date + pd.Timedelta(weeks=1), periods=FORECAST_STEPS, freq='W')
        
        forecast_df = pd.DataFrame({
            'ds': forecast_dates,
            'yhat': forecast_values.flatten(),
            'yhat_lower': forecast_values.flatten(),
            'yhat_upper': forecast_values.flatten() 
        })

        # Convert timestamps to ISO strings so they are JSON serializable
        forecast_df['ds'] = forecast_df['ds'].dt.strftime('%Y-%m-%d')

        print(f"✅ TensorFlow forecast generated successfully for the next {FORECAST_STEPS} {FREQ}.")

        # Return a JSON-friendly structure (list of records). The API layer can `jsonify` this directly.
        return forecast_df.to_dict(orient='records')

    except Exception as e:
        print(f"❌ FORECASTING_ERROR: An error occurred during TensorFlow forecasting: {e}")
        return None