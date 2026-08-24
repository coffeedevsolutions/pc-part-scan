import { Db, MongoClient } from "mongodb";

let client: MongoClient | null = null;

export function getDb(): Db {
  if (!client) {
    const uri = process.env.MONGODB_URI;
    if (!uri) throw new Error("MONGODB_URI is not set");
    client = new MongoClient(uri, { appName: "pcps-web" });
  }
  return client.db(process.env.PCPS_DB ?? "pcps");
}
