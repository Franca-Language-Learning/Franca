import { setupServer } from "msw/node";
import { handlersFromContract } from "./handlers";

export const server = setupServer(...handlersFromContract());
