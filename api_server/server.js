// WebSocket Server (Express.js / Socket.IO) - Kafka Consumer -> WebSocket
// Consumes trace data and location-magnitude results from Kafka and broadcasts
// them to connected WebSocket clients.

const { Kafka } = require('kafkajs');
const express = require("express");
const http = require("http");
const socketIo = require("socket.io");
const cors = require("cors");

// --- Prometheus Metrics ---
const promClient = require('prom-client');
const ENABLE_METRICS = (process.env.ENABLE_METRICS || 'true').toLowerCase() === 'true';
const METRICS_PORT = parseInt(process.env.METRICS_PORT_API_SERVER || '8107');

let wsBroadcastTotal, wsClientConnections, wsClientDisconnections, wsActiveClients, wsBroadcastLatency;

if (ENABLE_METRICS) {
  // Collect default Node.js metrics (CPU, memory, event loop, etc.)
  promClient.collectDefaultMetrics({ prefix: 'ws_server_' });

  wsBroadcastTotal = new promClient.Counter({
    name: 'ws_messages_broadcast_total',
    help: 'Total number of messages broadcast to WebSocket clients',
    labelNames: ['topic']
  });

  wsClientConnections = new promClient.Counter({
    name: 'ws_client_connections_total',
    help: 'Total number of WebSocket client connections'
  });

  wsClientDisconnections = new promClient.Counter({
    name: 'ws_client_disconnections_total',
    help: 'Total number of WebSocket client disconnections'
  });

  wsActiveClients = new promClient.Gauge({
    name: 'ws_active_clients',
    help: 'Number of currently connected WebSocket clients'
  });

  wsBroadcastLatency = new promClient.Histogram({
    name: 'ws_broadcast_latency_seconds',
    help: 'Latency of broadcasting a message to all clients',
    buckets: [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
  });
}

const app = express();
const server = http.createServer(app);
const io = socketIo(server);
const metricsApp = express();

const KAFKA_BROKERS = (process.env.KAFKA_BROKERS_ALL || 'kafka1:9092,kafka2:9093,kafka3:9094').split(',');
const KAFKA_TOPIC_TRACE = process.env.KAFKA_TOPIC_TRACE || 'trace_topic';
const KAFKA_TOPIC_RESULT = process.env.KAFKA_TOPIC_RESULT || 'result_loc_mag_topic';

const initializeConsumer = async () => {
  console.log("Initializing Kafka consumer for trace_topic...");
  const kafka = new Kafka({
    clientId: 'api-server',
    brokers: KAFKA_BROKERS
  });

  const consumer = kafka.consumer({ groupId: 'api-server-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: KAFKA_TOPIC_TRACE, fromBeginning: false });
  return consumer;
}

const initializeConsumer2 = async () => {
  console.log("Initializing Kafka consumer for result_loc_mag_topic...");
  const kafka = new Kafka({
    clientId: 'api-server2',
    brokers: KAFKA_BROKERS
  });

  const consumer2 = kafka.consumer({ groupId: 'api-server-group2' });
  await consumer2.connect();
  await consumer2.subscribe({ topic: KAFKA_TOPIC_RESULT, fromBeginning: false });
  return consumer2;
}

const initializeWebSocket = (consumer) => {
  console.log("Initializing WebSocket for trace_topic...");
  const clients = new Set();

  io.on("connection", (socket) => {
    console.log("A client connected.");
    clients.add(socket);
    if (ENABLE_METRICS) {
      wsClientConnections.inc();
      wsActiveClients.set(clients.size);
    }

    socket.on("disconnect", () => {
      console.log("A client disconnected.");
      clients.delete(socket);
      if (ENABLE_METRICS) {
        wsClientDisconnections.inc();
        wsActiveClients.set(clients.size);
      }
    });
  });

  consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      const data = JSON.parse(message.value);
      data['api_time'] = new Date().getTime();
      console.log(`Key: ${message.key},\tPartition ${partition},\tStation: ${data["station"]},\tChannel: ${data["channel"]}`);

      // Use process.hrtime.bigint() for nanosecond resolution (avoids 1ms floor of Date.now())
      const broadcastStart = process.hrtime.bigint();
      const endpoint = 'waves-data';

      for (let client of clients) {
        client.emit(endpoint, data);
      }

      if (ENABLE_METRICS) {
        wsBroadcastTotal.labels('trace_topic').inc();
        const broadcastNs = Number(process.hrtime.bigint() - broadcastStart);
        wsBroadcastLatency.observe(broadcastNs / 1e9);
      }
    },
  });
}

const initializeWebSocket2 = (consumer2) => {
  console.log("Initializing WebSocket for result_loc_mag_topic...");
  const clients = new Set();

  io.on("connection", (socket) => {
    clients.add(socket);

    socket.on("disconnect", () => {
      clients.delete(socket);
    });
  });

  consumer2.run({
    eachMessage: async ({ topic, partition, message }) => {
      const data = JSON.parse(message.value);
      data['api_time'] = new Date().getTime();
      console.log(`Key: ${message.key},\tPartition ${partition},\tStation: ${data["station"]},\tChannel: ${data["channel"]}\tloc_mag: ${data["predictions_loc_mag"]}`);

      // Use process.hrtime.bigint() for nanosecond resolution (avoids 1ms floor of Date.now())
      const broadcastStart2 = process.hrtime.bigint();
      const endpoint = 'loc-mag-data';

      for (let client of clients) {
        client.emit(endpoint, data);
      }

      if (ENABLE_METRICS) {
        wsBroadcastTotal.labels('result_loc_mag_topic').inc();
        const broadcastNs2 = Number(process.hrtime.bigint() - broadcastStart2);
        wsBroadcastLatency.observe(broadcastNs2 / 1e9);
      }
    },
  });
}

const main = async () => {
  app.use(cors());

  // --- Prometheus metrics server ---
  if (ENABLE_METRICS) {
    metricsApp.get('/metrics', async (req, res) => {
      try {
        res.set('Content-Type', promClient.register.contentType);
        res.end(await promClient.register.metrics());
      } catch (err) {
        res.status(500).end(err.message);
      }
    });
    metricsApp.listen(METRICS_PORT, () => {
      console.log(`[ApiServer] Prometheus metrics server listening on port ${METRICS_PORT}`);
    });
  }

  // Health check
  app.get('/health', (req, res) => {
    res.json({ status: 'healthy' });
  });

  const consumer = await initializeConsumer();
  const consumer2 = await initializeConsumer2();
  initializeWebSocket(consumer);
  initializeWebSocket2(consumer2);

  app.get("/", (req, res) => {
    res.sendFile(__dirname + "/public/index.html");
  });

  server.listen(3333, () => {
    console.log("Server is running on port 3333");
  });
}

main();
