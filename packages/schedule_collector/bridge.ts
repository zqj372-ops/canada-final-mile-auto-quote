// Built against a pinned copy of the existing public schedule collector.
// The @collector imports are resolved by scripts/build_schedule_collector.mjs.
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { createCollectorService } from '@collector/service';
import { parseCollectorQueryInput } from '@collector/contracts';
import { FileEvidenceStore } from '@collector/evidence';
import { createControlledHttpTransport } from '@collector/transport/http';
import { createNodePinnedConnector } from '@collector/transport/node-connector';
import { createOneLiveTransportPolicy } from '@collector/transport/one-live';
import { createCoscoLiveTransportPolicy } from '@collector/transport/cosco-live';

const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 50000);
process.once('SIGTERM', () => controller.abort());
try {
  const input = parseCollectorQueryInput(JSON.parse(readFileSync(0, 'utf8')));
  if (!['ONE', 'COSCO'].includes(input.carrier)) throw new Error('unsupported_carrier');
  const policy = input.carrier === 'ONE' ? createOneLiveTransportPolicy() : createCoscoLiveTransportPolicy();
  const service = createCollectorService({ deadlineMs: 50000, ports: {
    clock: { now: () => new Date() },
    context: { requestId: `quote-schedule-${randomUUID()}`, auditId: `schedule-${randomUUID()}`, localFixture: false },
    audit: { record: async () => {} },
    evidence: new FileEvidenceStore({ root: resolve(process.cwd(), 'evidence') }),
    http: createControlledHttpTransport({ policy, connector: createNodePinnedConnector({
      maxResponseBytes: policy.maxResponseBytes, timeoutMs: 20000,
    }) }),
  }});
  let pending = null;
  for (const side of ['origin', 'destination'] as const) {
    const loc = input[side];
    const result = await service.resolveLocations({carrier: input.carrier, text: loc.text,
      countryCode: loc.country_code, locationId: loc.carrier_location_id}, {signal: controller.signal});
    const envelope = result.envelope as any;
    if (envelope.status !== 'success') {
      pending = {...envelope, pending_side: side};
      break;
    }
  }
  const result = pending ?? (await service.query(input, {signal: controller.signal})).envelope;
  process.stdout.write(JSON.stringify(result));
} catch {
  process.stdout.write(JSON.stringify({status:'unavailable',data:null,blockers:[{code:'collector_failed'}]}));
  process.exitCode = 1;
} finally { clearTimeout(timer); }
