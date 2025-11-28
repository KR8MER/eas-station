#!/usr/bin/env python3
"""
Fix for audio squeal issue in Icecast streams.

The issue is likely caused by a sample rate mismatch in the audio demodulation pipeline.
This script checks and fixes the configuration.
"""

import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def check_and_fix():
    """Check for audio configuration issues and fix them."""

    logger.info("=" * 80)
    logger.info("EAS Station Audio Squeal Diagnostic and Fix")
    logger.info("=" * 80)

    try:
        # Import app and database
        from app import create_app
        from app_core.extensions import db
        from app_core.models import AudioSourceConfigDB, RadioReceiver

        app = create_app()

        with app.app_context():
            logger.info("\n1. Checking RadioReceiver configurations...")
            receivers = RadioReceiver.query.all()

            for receiver in receivers:
                logger.info(f"\nReceiver: {receiver.identifier} ({receiver.display_name})")
                logger.info(f"  - Driver: {receiver.driver}")
                logger.info(f"  - Frequency: {receiver.frequency_hz / 1e6:.3f} MHz")
                logger.info(f"  - Modulation: {receiver.modulation_type}")
                logger.info(f"  - Audio Output: {receiver.audio_output}")
                logger.info(f"  - Stereo: {receiver.stereo_enabled}")
                logger.info(f"  - Sample Rate (IQ): {receiver.sample_rate} Hz")

                # Check if sample rate looks suspicious
                if receiver.sample_rate < 100000:
                    logger.warning(f"  ⚠️  WARNING: IQ sample rate {receiver.sample_rate} Hz seems very low!")
                    logger.warning(f"     This should typically be 1-3 MHz for SDR receivers")
                    logger.warning(f"     Current value looks like an audio rate, not an IQ rate!")

                    # Fix: Set to appropriate IQ sample rate
                    if receiver.driver in ['rtlsdr', 'airspy', 'hackrf', 'sdrplay']:
                        recommended_iq_rate = 2400000  # 2.4 MHz is common
                        logger.info(f"  🔧 Fixing IQ sample rate to {recommended_iq_rate} Hz")
                        receiver.sample_rate = recommended_iq_rate
                        db.session.add(receiver)

            logger.info("\n2. Checking AudioSourceConfig configurations...")
            audio_sources = AudioSourceConfigDB.query.all()

            for source in audio_sources:
                logger.info(f"\nAudio Source: {source.name}")
                logger.info(f"  - Type: {source.source_type}")
                logger.info(f"  - Enabled: {source.enabled}")
                logger.info(f"  - Auto Start: {source.auto_start}")

                config_params = source.config_params or {}
                sample_rate = config_params.get('sample_rate', 44100)
                channels = config_params.get('channels', 1)

                logger.info(f"  - Audio Sample Rate: {sample_rate} Hz")
                logger.info(f"  - Channels: {channels}")

                # For SDR sources, verify the audio sample rate is reasonable
                if source.source_type == 'sdr':
                    receiver_id = config_params.get('device_params', {}).get('receiver_id')
                    if receiver_id:
                        receiver = RadioReceiver.query.filter_by(identifier=receiver_id).first()
                        if receiver:
                            # Check recommended sample rate
                            mod = (receiver.modulation_type or 'IQ').upper()

                            if mod in {'FM', 'WFM'}:
                                recommended = 48000 if receiver.stereo_enabled else 32000
                                recommended_ch = 2 if receiver.stereo_enabled else 1
                            elif mod in {'AM', 'NFM'}:
                                recommended = 24000
                                recommended_ch = 1
                            else:
                                recommended = 44100
                                recommended_ch = 1

                            if sample_rate != recommended or channels != recommended_ch:
                                logger.warning(f"  ⚠️  Audio config mismatch!")
                                logger.warning(f"     Current: {sample_rate} Hz, {channels} ch")
                                logger.warning(f"     Recommended for {mod}: {recommended} Hz, {recommended_ch} ch")
                                logger.info(f"  🔧 Fixing audio configuration...")

                                config_params['sample_rate'] = recommended
                                config_params['channels'] = recommended_ch
                                source.config_params = config_params
                                db.session.add(source)

            # Commit all changes
            if db.session.dirty:
                logger.info("\n3. Committing configuration fixes...")
                db.session.commit()
                logger.info("✅ Configuration fixes applied successfully!")
                logger.info("\n⚠️  IMPORTANT: You must restart the audio service for changes to take effect:")
                logger.info("   docker-compose restart sdr-service")
            else:
                logger.info("\n✅ No configuration issues found!")

            logger.info("\n" + "=" * 80)
            logger.info("Diagnostic complete!")
            logger.info("=" * 80)

            return 0

    except Exception as e:
        logger.error(f"❌ Error during diagnostic: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(check_and_fix())
