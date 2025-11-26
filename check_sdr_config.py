#!/usr/bin/env python3
"""Diagnostic script to check SDR receiver configuration."""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Direct database access without Flask app context
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app_core.models import RadioReceiver

def main():
    # Get database connection from environment
    db_host = os.environ.get('POSTGRES_HOST', 'localhost')
    db_port = os.environ.get('POSTGRES_PORT', '5432')
    db_name = os.environ.get('POSTGRES_DB', 'alerts')
    db_user = os.environ.get('POSTGRES_USER', 'postgres')
    db_pass = os.environ.get('POSTGRES_PASSWORD', 'postgres')

    database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        receivers = session.query(RadioReceiver).filter_by(enabled=True).all()

        print("=" * 70)
        print("SDR RECEIVER CONFIGURATION DIAGNOSTIC")
        print("=" * 70)

        for rx in receivers:
            print(f"\nReceiver: {rx.name} (ID: {rx.identifier})")
            print(f"  Driver: {rx.driver}")
            print(f"  Frequency: {rx.frequency_hz / 1e6:.3f} MHz")
            print(f"  Sample Rate: {rx.sample_rate / 1e6:.3f} MHz ({rx.sample_rate:,} Hz)")
            print(f"  Gain: {rx.gain}")
            print(f"  Serial: {rx.serial}")
            print(f"  Modulation: {rx.modulation_type}")
            print(f"  Auto Start: {rx.auto_start}")

            # Check if sample rate is compatible with AirSpy
            if rx.driver == 'airspy':
                airspy_rates = [2500000, 10000000]  # 2.5 MHz, 10 MHz
                # Add decimated rates
                for base in airspy_rates:
                    for div in [1, 2, 4, 8, 16]:
                        airspy_rates.append(base // div)

                if rx.sample_rate in airspy_rates:
                    print(f"  ✅ Sample rate {rx.sample_rate:,} Hz is COMPATIBLE with AirSpy")
                else:
                    print(f"  ⚠️  Sample rate {rx.sample_rate:,} Hz may be INCOMPATIBLE with AirSpy")
                    print(f"  Recommended AirSpy sample rates:")
                    sorted_rates = sorted(set(airspy_rates), reverse=True)
                    for rate in sorted_rates[:10]:
                        print(f"    - {rate / 1e6:.3f} MHz ({rate:,} Hz)")

        print("\n" + "=" * 70)
    finally:
        session.close()

if __name__ == "__main__":
    main()
