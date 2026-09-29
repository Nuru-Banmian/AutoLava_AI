// A request belongs to the authentication generation in which it started.
// Increment before changing credentials so an old response cannot populate a new session.
let generation = 0;

export function currentSessionScope(): number {
  return generation;
}

export function advanceSessionScope(): number {
  generation += 1;
  return generation;
}

export class StaleSessionError extends Error {
  constructor() {
    super("The authentication session changed");
    this.name = "StaleSessionError";
  }
}

export function assertSessionScope(scope: number): void {
  if (scope !== generation) throw new StaleSessionError();
}
