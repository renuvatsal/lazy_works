# main.py
import os
import requests
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Any issues/errors in script?
# Fix it yourself
# --- Configuration ---
#logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

#loading env file
# This ensures the script finds the.env file even when run from a different directory.
script_dir = Path(__file__).resolve().parent
dotenv_path = script_dir / 'vatsal.env'
load_dotenv(dotenv_path=dotenv_path)

class CultFitAPIClient:
    """
    A client for interacting with the unofficial cult.fit API, updated for robustness.
    """
    BASE_URL = "https://www.cult.fit/api"

    def __init__(self, api_key, at_token, st_token):
        if not all([api_key, at_token, st_token]):
            raise ValueError("API key and authentication tokens are required.")
        
        self.session = requests.Session()
        # Set the authentication headers and cookies that will be used for all requests
        self.session.headers.update({
            "apiKey": api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
        })
        self.session.cookies.update({
            "at": at_token,
            "st": st_token
        })

    def get_available_classes(self, center_id: str, date: str) -> list:
        """
        Fetches the list of available classes for a given center and date.

        Args:
            center_id: The ID of the fitness center.
            date: The date in 'YYYY-MM-DD' format.

        Returns:
            - A list of class dictionaries if the date is available.
            - None if the date is not yet available for booking.
            - 'AUTH_ERROR' string if authentication fails.
        """
        endpoint = f"{self.BASE_URL}/cult/classes"
        params = {
            "center": center_id
        }
        logging.info(f"Fetching classes for center {center_id} on {date}...")
        try:
            response = self.session.get(endpoint, params=params)

            # Check for authentication errors first
            if response.status_code != 200:
                logging.error("Authentication failed (401/403). Your 'at' and 'st' tokens have likely expired.")
                logging.error("Please log in to cult.fit manually and update your environment file with new tokens.")
                return 'AUTH_ERROR'

            response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)
            
            data = response.json()
            class_by_date_list = data.get("classByDateList",)

            # Find the schedule for the target date
            for day_schedule in class_by_date_list:
                if day_schedule.get("id") == date:
                    class_list = []
                    class_by_time_list = day_schedule.get("classByTimeList",)
                    
                    for time_slot in class_by_time_list:
                        class_list.extend(time_slot.get("classes",))
                        
                    logging.info(f"Found {len(class_list)} total classes for the target date {date}.")
                    return class_list
                
                # If the loop completes without finding the date, it's not available yet
            logging.info(f"Target date {date} is not yet available for booking.")
            return None

        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch classes: {e}")
            if 'response' in locals():
                logging.error(f"Response content: {response.text}")
            else:
                logging.error("No response received from server.")
            return # Return empty list on general network failure to avoid stopping the loop
        
    def find_target_class(self, classes: list, time_str: str, workout_name: str) -> dict | None:
        """
        Finds a specific class from a list based on time and workout name.
        """
        logging.info(f"Searching for workout '{workout_name}' at {time_str}...")
        for cls in classes:
            is_bookable = cls.get("state") == "AVAILABLE"
            has_seats = cls.get("availableSeats", 0) > 0
            
            # Ensure the time format in your.env file matches the API (e.g., "19:00:00")
            matches_time = cls.get("startTime") == time_str
            matches_name = cls.get("workoutName") == workout_name

            if is_bookable and has_seats and matches_time and matches_name:
                logging.info(f"Found matching class: ID {cls.get('id')}, Seats: {cls.get('availableSeats')}")
                return cls
        
        logging.warning("No matching, available class found for the specified criteria.")
        return None

    def book_class(self, class_id: str) -> bool:
        """
        Attempts to book a class using its ID.
        """
        endpoint = f"{self.BASE_URL}/cult/class/{class_id}/book"
        logging.info(f"Attempting to book class with ID: {class_id}")
        try:
            response = self.session.post(endpoint)
            
            if response.status_code == 200:
                logging.info("Successfully booked class!")
                return True
            else:
                logging.error(f"Booking failed. Status code: {response.status_code}")
                logging.error(f"Response: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"An error occurred during booking request: {e}")
            return False

def main():
    """
    Main execution function for the booking bot with recursive checking.
    """
    logging.info("--- Cult.fit Booking Bot Started ---")
    
    # --- Retrieve Credentials ---
    api_key = os.getenv("CULT_API_KEY")
    at_token = os.getenv("CULT_AT_TOKEN")
    st_token = os.getenv("CULT_ST_TOKEN")
    center_id = os.getenv("CENTER_ID")
    preferred_time = os.getenv("PREFERRED_TIME")
    workout_name = os.getenv("PREFERRED_WORKOUT_NAME")
    advance = int(os.getenv("DAYS_IN_ADVANCE"))
    
    try:
        client = CultFitAPIClient(api_key, at_token, st_token)
    except ValueError as e:
        logging.error(f"Initialization failed: {e}. Please check your environment file.")
        return

    # --- Determine Target Date ---
    target_date = datetime.now() + timedelta(days=advance)
    date_str = target_date.strftime("%Y-%m-%d")

    # --- Execute Booking Workflow ---
    while True:
        available_classes = client.get_available_classes(center_id, date_str)

        # Case 1: Authentication failed, terminate the script.
        if available_classes == 'AUTH_ERROR':
            logging.error("Terminating script due to authentication failure.")
            break

        # Case 2: Date is not available yet, and we are booking 4 days in advance. Wait and retry.
        if available_classes is None and advance == 4:
            logging.info("Booking date not yet available. Retrying in 3 minutes...")
            time.sleep(180)  # Wait for 3 minutes
            continue
        
        # Case 3: Date is available, but no classes were found or a network error occurred.
        if not available_classes:
            logging.warning("Could not retrieve any classes for the target date. Exiting.")
            break
        
        # Case 4: Date and classes are available, proceed with booking.
        target_class = client.find_target_class(available_classes, preferred_time, workout_name)
    
        if target_class and 'id' in target_class:
            success = client.book_class(target_class['id'])
            if success:
                logging.info("Booking successful. Terminating script.")
                break  # Exit the loop on successful booking
        else:
            logging.info("No target class found to book. Exiting.")
            break # Exit if the desired class isn't on the schedule
        
        # Fallback sleep to prevent rapid-fire failed booking attempts if something goes wrong
        logging.warning("Booking attempt failed. Retrying in 3 minutes...")
        time.sleep(180)

    logging.info("--- Cult.fit Booking Bot Finished ---")

if __name__ == "__main__":
    main()
