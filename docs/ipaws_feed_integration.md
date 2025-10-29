# IPAWS Feed and Pub/Sub Integration Overview

This document distills guidance received from the IPAWS Program Management Office and
outlines concrete ways our NOAA Alerts System can leverage the provided feeds and the AWS
Simple Notification Service (SNS) pilot.

## Key Takeaways

- IPAWS exposes unauthenticated REST feeds for Emergency Alert System (EAS), Non-Weather
  Emergency Messages (NWEM), Wireless Emergency Alerts (WEA), and the aggregated Public feed.
- Vendors should poll staging feeds first, no more frequently than every two minutes, and
  cache responses before redistributing alerts to end users.
- Feeds return CAP XML payloads; the shared poller now parses those documents (including
  polygons, circles, and SAME geocodes) into the existing alert ingestion workflow without
  requiring separate code paths.
- Alerts stored in PostGIS are now stamped with their originating feed (NOAA, IPAWS, or manual)
  and the poller logs duplicate identifiers filtered from multi-feed runs.
- IPAWS is piloting SNS topics that mirror the public feed to support push-style
  integrations. Subscription options include email, HTTPS webhooks, and several AWS-native
  targets.

## REST Feed Consumption Strategy

1. **Start in Staging**  
   Use the provided staging URLs during development and QA:

   - `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/eas/recent/<timestamp>`
   - `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/nwem/recent/<timestamp>`
   - `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/PublicWEA/recent/<timestamp>`
   - `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/<timestamp>`
   - `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public_non_eas/recent/<timestamp>`

   Replace `<timestamp>` with the ISO-8601 marker for the most recent alert we processed.

2. **Implement Back-off and Caching**  
   - Respect the two-minute polling guidance to avoid throttling.
   - Store the raw CAP XML payloads in our database or object storage for downstream
     dissemination.
   - De-duplicate by `identifier` and `sent` timestamp to prevent replay. The shared poller
     performs this automatically and records how many duplicates were discarded each cycle.

3. **Redistribute Internally**  
   - Surface alerts through our existing WebSocket, REST, and LED sign delivery pipelines.
   - Maintain audit logs noting the source feed and retrieval time.

4. **Transition to Production**  
   Once staging integration is validated, swap the base domain to `https://apps.fema.gov`
   and monitor for differences in volume or schema.

## SNS Pub/Sub Integration Strategy

1. **Subscription Setup**  
   - Request addition of our preferred endpoint (e.g., HTTPS webhook or Amazon Kinesis Data
     Firehose) to the `EAS_PUBLIC_FEED` topic via the IPAWS engineering team.
   - Ensure the endpoint can receive and acknowledge SNS subscription confirmation
     messages.

2. **Message Handling**  
   - SNS delivers the same payloads as the Public feed. Validate the message signature,
     parse the CAP alert, and persist it via our existing ingestion pipeline.
   - Consider using SNS as a trigger to accelerate pull-based refreshes when the polling
     interval is too coarse.

3. **Fallback and Monitoring**  
   - Keep the REST polling flow active as a fallback until SNS topics reach parity for all
     desired dissemination channels.
   - Instrument metrics on delivery latency, failures, and retry counts.

## Next Steps for Our Team

- Prototype a staging poller that uses the public feed, respects caching guidance, and
  hydrates our internal models.
- Evaluate the HTTPS SNS subscription path by exposing a webhook endpoint (e.g.,
  `/api/ipaws/sns`) capable of processing confirmation and notification messages.
- Coordinate with the IPAWS Engineering Branch (fema-ipaws-eng@fema.dhs.gov) to register
  our staging subscription and confirm production onboarding requirements.

## Additional Resources

- [IPAWS All-Hazard Info Feed overview](https://www.fema.gov/about/offices/national-continuity-programs/integrated-public-alert-warning-system/open-platform-emergency-networks)
- [AWS SNS HTTP/HTTPS endpoint setup guide](https://docs.aws.amazon.com/sns/latest/dg/sns-http-https-endpoint-as-subscriber.html)

