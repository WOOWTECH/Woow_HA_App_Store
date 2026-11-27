// Agent Connect's managed daemon takes its identity from the host's selected
// target, never from a remote client's hello. Activation supplies this variable;
// target switching stops the previous daemon before starting the next identity.
const brands = Object.freeze({
  paseo: Object.freeze({ id: 'paseo', name: 'Paseo' }),
  woowtech: Object.freeze({ id: 'woowtech', name: 'Woowtech Smart' }),
  apporo: Object.freeze({ id: 'apporo', name: 'Apporo Smart' }),
});
export function selectedBrand(target = process.env.PI_PASEO_CONNECTION_TARGET ?? 'paseo') {
  if (!Object.hasOwn(brands, target)) throw Object.assign(new Error('INVALID_CONNECTION_TARGET'), { code: 'INVALID_CONNECTION_TARGET' });
  return brands[target];
}
export const agentConnectBrand = selectedBrand();
