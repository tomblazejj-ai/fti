/**
 * Entry point of the FTI cloud Worker — the logic and its documentation are in ./app.ts and ./dispatch.ts.
 * (The Workers runtime treats every named export of this file as an entry point, so only the handler is exported here.)
 */
import { type Env, d1Store, handle } from "./app";
import { dispatch } from "./dispatch";

export default {
  fetch(req, env) {
    return handle(req, env, d1Store(env.DB));
  },
  // every 30 minutes: ask GitHub to run the FTI cycle (GitHub's own schedule is best effort)
  async scheduled(_event, env) {
    const r = await dispatch(env);
    console.log(r.text);
  },
} satisfies ExportedHandler<Env>;
