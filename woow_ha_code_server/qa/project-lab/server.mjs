import {start} from './runtime.mjs';
import {fileURLToPath} from 'node:url';
await start({root:fileURLToPath(new URL('./',import.meta.url))});
