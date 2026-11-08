/**
 * Entry point of the FTI cloud Worker — the logic and its documentation are in ./app.ts.
 * (The Workers runtime treats every named export of this file as an entry point, so only the handler is exported here.)
 */
import { type Env, d1Store, handle } from "./app";

export default {
  fetch(req, env) {
    return handle(req, env, d1Store(env.DB));
  },
} satisfies ExportedHandler<Env>;
