import pytest

from src.common.config import Config, CredentialsConfig, TargetConfig, ScheduleConfig
from src.common.models import ReservationTarget


@pytest.fixture()
def config():
    return Config(
        credentials=CredentialsConfig(email="test@example.com", password="secret"),
        target=TargetConfig(
            campground_id="100",
            campsite_ids=["A1", "B2"],
            arrival_date="2030-08-01",
            departure_date="2030-08-03",
        ),
        schedule=ScheduleConfig(window_opens="2030-08-01 07:00:00"),
    )


@pytest.fixture()
def target(config):
    return ReservationTarget(
        campground_id=config.target.campground_id,
        campsite_ids=config.target.campsite_ids,
        arrival_date=config.target.arrival.date(),
        departure_date=config.target.departure.date(),
    )

