import requests
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from partials.head import head
from partials.dark_mode_toggle import dark_mode_toggle
from partials.toast import toast
from partials.notification import notification
from partials.header import header
from partials.overview import overview
from partials.faq import faq
from partials.churn_schedule import churn_schedule
from partials.historical_charts import historical_charts
from partials.historical_data_json import historical_data_json
from partials.footer import footer

load_dotenv()
PECTRIFIED_TOKEN = os.environ.get("PECTRIFIED_TOKEN")
PECTRIFIED_URL = os.environ.get("PECTRIFIED_URL")

if not PECTRIFIED_TOKEN or not PECTRIFIED_URL:
    print("PECTRIFIED_TOKEN and PECTRIFIED_URL must both be set")
    sys.exit(1)

GWEI_PER_ETH = 1_000_000_000


###############
# FOR TESTING
###############


def generate_base_html():
    html_content = f"""<!DOCTYPE html>
		<html lang="en">
		{head}
		<body>
			{dark_mode_toggle}
			{toast()}
			{notification()}
			<div class="container">
				{footer()}
			</div>
		</body>
		</html>"""
    with open("public/index.html", "w") as f:
        f.write(html_content)
    sys.exit()


# generate_base_html()

###############


api_url = f"{PECTRIFIED_URL}/validator-queue"
response = None
try:
    response = requests.get(
        api_url, headers={"X-Pectrified-Auth": PECTRIFIED_TOKEN}, timeout=30
    )
    response.raise_for_status()
    api_data = response.json()
    print(f"API response keys: {list(api_data.keys())}")
except Exception as e:
    print(f"Error fetching validator queue data: {e}")
    if response is not None:
        print(f"Response: {response.text[:500]}")
    sys.exit(1)

metadata = api_data["metadata"]
current_time = datetime.now(timezone.utc).timestamp()


def format_wait_time(wait_days):
    """Convert a wait time in days (the API's metadata unit) to a human-readable string."""
    if wait_days == 0:
        return "— no queue"
    total_seconds = round(wait_days * 86400)

    days = total_seconds // 86400
    days_hours = round((total_seconds % 86400) / 86400 * 24)

    hours = total_seconds // 3600
    hours_minutes = round((total_seconds % 3600) / 3600 * 60)

    if days > 0:
        days_text = "day" if days == 1 else "days"
        hours_text = "hour" if days_hours == 1 else "hours"
        return f"{days} {days_text}, {days_hours} {hours_text}"
    elif hours > 0:
        hours_text = "hour" if hours == 1 else "hours"
        minutes_text = "minute" if hours_minutes == 1 else "minutes"
        return f"{hours} {hours_text}, {hours_minutes} {minutes_text}"
    else:
        minutes_text = "minute" if hours_minutes == 1 else "minutes"
        return f"{hours_minutes} {minutes_text}"


entry_queue_eth = round(metadata["entry_queue"] / GWEI_PER_ETH)
entry_wait_str = format_wait_time(metadata["entry_wait"])
exit_queue_eth = round(metadata["exit_queue"] / GWEI_PER_ETH)
exit_wait_str = format_wait_time(metadata["exit_wait"])
entry_churn = metadata["churn_activation_per_epoch"]
exit_churn = metadata["churn_exit_per_epoch"]
active_validators = metadata["active_validators"]
amount_eth_staked = round(metadata["staked_eth"])
percent_eth_staked = metadata.get("staked_percent") or 0
staking_apr = metadata.get("apr") or 0


def epoch_ms_to_date(epoch_ms):
    """Convert epoch milliseconds to 'YYYY-MM-DD' string."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


NULL_CREDENTIAL_FIELDS = {"total": None, "0x00": None, "0x01": None, "0x02": None}


def build_historical_data(api_data):
    """Convert API chart series arrays into daily historical_data and historical_conversion_data objects."""
    meta = api_data["metadata"]
    vq = api_data["validatorQueue"]
    qw = api_data["queueWaitTime"]
    av = api_data["activeValidators"]
    cr = api_data["credentials"]
    ss = api_data["supplyStaked"]
    sa = api_data["stakingApr"]

    # All series except stakingApr are element-wise maps over the same time base,
    # so they are index-aligned. stakingApr has nulls filtered out and must be
    # joined by date instead.
    time_series = vq["time"]

    # Group indices by date, take the first index per day
    date_indices = {}
    for i, ts in enumerate(time_series):
        date_str = epoch_ms_to_date(ts)
        if date_str not in date_indices:
            date_indices[date_str] = i

    sorted_dates = sorted(date_indices.keys())
    indices = [date_indices[d] for d in sorted_dates]

    apr_by_date = {}
    for ai, ats in enumerate(sa["time"]):
        apr_by_date[epoch_ms_to_date(ats)] = sa["apr"][ai]

    historical_data = []
    historical_conversion_data = []

    for idx in indices:
        date_str = epoch_ms_to_date(time_series[idx])
        staked_percent = ss["percent"][idx]
        total_eth = ss["totalEth"][idx]

        historical_data.append(
            {
                "date": date_str,
                "validators": av["count"][idx],
                "entry_queue": round(vq["entry"][idx]),
                "entry_wait": round(qw["entry"][idx], 2),
                "exit_queue": round(vq["exit"][idx]),
                "exit_wait": round(qw["exit"][idx], 2),
                "current_entry_churn": meta["churn_activation_per_epoch"],
                "current_exit_churn": meta["churn_exit_per_epoch"],
                "ave_entry_churn": meta["churn_activation_per_epoch"],
                "ave_exit_churn": meta["churn_exit_per_epoch"],
                # not read by any chart; the API exposes no supply series
                "supply": None,
                "staked_amount": round(total_eth),
                "staked_percent": round(staked_percent, 2)
                if staked_percent is not None
                else None,
                "apr": apr_by_date.get(date_str),
            }
        )

        # credentialsPercentChart uses value[type] / value.total, so only the
        # ratio matters. count/change/slot are read by nothing (the Credentials Δ
        # card is commented out) and stay null rather than being invented.
        historical_conversion_data.append(
            {
                "date": date_str,
                "slot": None,
                "count": dict(NULL_CREDENTIAL_FIELDS),
                "change": dict(NULL_CREDENTIAL_FIELDS),
                "value": {
                    "total": round(total_eth),
                    "0x00": round(total_eth * cr["0x00"][idx] / 100),
                    "0x01": round(total_eth * cr["0x01"][idx] / 100),
                    "0x02": round(total_eth * cr["0x02"][idx] / 100),
                },
            }
        )

    return historical_data, historical_conversion_data


def generate_html(
    entry_waiting_time,
    beaconchain_entering,
    exit_waiting_time,
    beaconchain_exiting,
    active_validators,
    entry_churn,
    exit_churn,
    amount_eth_staked,
    percent_eth_staked,
    staking_apr,
    historical_data,
    historical_conversion_data,
):
    html_content = f"""<!DOCTYPE html>
		<html lang="en">
		{head}
		<body>
			{dark_mode_toggle}
			{toast()}
			{notification()}
			<div class="container">
				{header(current_time)}
				{overview(entry_waiting_time, beaconchain_entering, exit_waiting_time, beaconchain_exiting, entry_churn, exit_churn, active_validators, amount_eth_staked, percent_eth_staked, staking_apr)}
				{faq}
				{churn_schedule(active_validators)}
				{historical_charts}
				{historical_data_json(historical_data, historical_conversion_data)}
				{footer()}
			</div>
		</body>
		</html>"""

    with open("public/index.html", "w") as f:
        f.write(html_content)


historical_data, historical_conversion_data = build_historical_data(api_data)

print(
    f"historical_data: {len(historical_data)} rows, {historical_data[0]['date']} -> {historical_data[-1]['date']}"
)
print(
    f"conversion_data: {len(historical_conversion_data)} rows, {historical_conversion_data[0]['date']} -> {historical_conversion_data[-1]['date']}"
)
print(
    f"entry: {entry_queue_eth} ETH, {entry_wait_str} | exit: {exit_queue_eth} ETH, {exit_wait_str}"
)

generate_html(
    entry_wait_str,
    entry_queue_eth,
    exit_wait_str,
    exit_queue_eth,
    active_validators,
    entry_churn,
    exit_churn,
    amount_eth_staked,
    percent_eth_staked,
    staking_apr,
    historical_data,
    historical_conversion_data,
)
