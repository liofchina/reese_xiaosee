(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    world: null,
    summaries: [],
    selectedId: "",
    regionId: "",
    personId: "",
    capabilities: null,
    allPeople: false,
    localEvents: false,
    busy: false,
    aiBusy: false,
    loading: false,
    polling: false,
    offline: false,
    preferredInterval: 15,
    mapWorldId: "",
    selectionToken: 0,
    ready: false,
    historyEvents: [],
    historyWorldId: "",
    historyNpcId: null,
    historyRegionId: null,
    historyNext: null,
    historyBusy: false,
    historyRequest: 0,
    factRequest: 0,
    pendingExperiment: null,
  };

  class APIError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  function node(tag, className = "", text = "") {
    const result = document.createElement(tag);
    result.className = className;
    result.textContent = text;
    return result;
  }

  function report(error) {
    console.error(error);
    const message = error instanceof Error ? error.message : "发生未知错误，请查看浏览器控制台。";
    if ($("fact-dialog").open) {
      $("fact-error").textContent = message;
      $("fact-error").hidden = false;
      return;
    }
    if ($("history-dialog").open) {
      $("history-error").textContent = message;
      $("history-error").hidden = false;
      return;
    }
    $("notice-text").textContent = message;
    $("notice").hidden = false;
  }

  function announce(message) {
    $("action-announcement").textContent = message;
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const aiRequest = /\/(chronicle|chat)$/.test(path);
    const timeout = setTimeout(() => controller.abort(), aiRequest ? 120000 : 15000);
    let response;
    try {
      response = await fetch(path, {
        method: options.method || "GET",
        headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      console.error(error);
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error(aiRequest
          ? "AI 请求等待超时。服务端可能仍在处理，请稍后同步世界，避免立即重复付费调用。"
          : "世界服务响应超时，请稍后重试。");
      }
      throw new Error("无法连接世界服务，请确认服务器正在运行。");
    } finally {
      clearTimeout(timeout);
    }
    if (response.status === 204) return null;
    let data;
    try {
      data = await response.json();
    } catch (error) {
      console.error(error);
      throw new APIError("服务未返回有效数据，请检查服务器日志。", response.status);
    }
    if (!response.ok) {
      const detail = typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((item) => item.msg).join("；")
          : `世界服务请求失败（${response.status}）。`;
      throw new APIError(detail, response.status);
    }
    return data;
  }

  function factionFor(id) {
    const faction = state.world.factions.find((item) => item.id === id);
    if (!faction) throw new Error("世界存档缺少对应势力，请检查存档。");
    return faction;
  }

  function regionFor(id) {
    const region = state.world.regions.find((item) => item.id === id);
    if (!region) throw new Error("世界存档缺少对应地点，请检查存档。");
    return region;
  }

  function selectedPerson() {
    return state.world ? state.world.npcs.find((item) => item.id === state.personId) : null;
  }

  function isLiving() {
    return state.world?.ruleset === "living";
  }

  function supportsHistory() {
    return state.capabilities?.persistent_history === true;
  }

  function professionFor(person) {
    return person.life ? state.capabilities.profession_names[person.life.profession] : person.trait;
  }

  function realmFor(person) {
    if (person.life) {
      return person.life.health === 0 ? "已逝" : person.life.ability ? "掌握引流" : "普通人";
    }
    return state.capabilities.realm_names[person.realm];
  }

  function goodsCopy(stock) {
    return Object.entries(state.capabilities.good_names)
      .map(([good, name]) => `${name}${stock[good]}`).join("，");
  }

  function entityName(id) {
    const world = state.world;
    if (!world) return id;
    if (id === "river") return "汀川河道";
    if (id.startsWith("market:")) return `${regionFor(id.slice(7)).name}货栈`;
    return [...world.npcs, ...world.regions, ...world.factions, ...(world.roads || [])]
      .find((entity) => entity.id === id)?.name || id;
  }

  function journeyCopy(person) {
    const journey = person.life?.journey;
    if (!journey) return `在${regionFor(person.region_id).name}`;
    const target = journey.returning ? person.region_id : journey.destination_id;
    return `${journey.returning ? "折返" : "前往"}${regionFor(target).name}，还需${journey.remaining_days}日`;
  }

  function replaceList(container, children) {
    const active = document.activeElement;
    const key = container.contains(active) ? active.dataset.focusKey : null;
    container.replaceChildren(...children);
    if (key) {
      const replacement = [...container.querySelectorAll("[data-focus-key]")]
        .find((item) => item.dataset.focusKey === key);
      if (replacement) replacement.focus({ preventScroll: true });
    }
  }

  function updateSummary(world) {
    const summary = {
      id: world.id, name: world.name, day: world.day, running: world.running,
      npc_count: world.npcs.length, updated_at: world.updated_at,
      ruleset: world.ruleset || "classic",
    };
    const index = state.summaries.findIndex((item) => item.id === world.id);
    if (index < 0) state.summaries.unshift(summary);
    else state.summaries[index] = summary;
  }

  function renderPicker() {
    const picker = $("world-select");
    if (!state.summaries.length) {
      picker.replaceChildren(node("option", "", "尚无世界，请先开辟"));
      picker.firstElementChild.value = "";
    } else {
      const currentIds = [...picker.options].map((item) => item.value).join(",");
      const nextIds = state.summaries.map((item) => item.id).join(",");
      if (currentIds !== nextIds) {
        picker.replaceChildren(...state.summaries.map((world) => {
          const option = node("option");
          option.value = world.id;
          return option;
        }));
      }
      state.summaries.forEach((world, index) => {
        picker.options[index].textContent = `${world.name} / 第${world.day}日`;
      });
      picker.value = state.selectedId;
    }
    picker.disabled = state.busy || state.aiBusy || state.loading || !state.summaries.length;
  }

  function renderControls() {
    const world = state.world;
    const unavailable = !world || state.busy || state.loading || state.offline;
    $("run-world").disabled = unavailable;
    $("step-world").disabled = unavailable || world.running;
    $("world-speed").disabled = unavailable;
    $("world-speed").value = String(state.preferredInterval);
    $("run-label").textContent = world && world.running ? "暂停世界" : "开始演化";
    $("run-icon").setAttribute("href", world && world.running ? "#i-pause" : "#i-play");
    $("new-world").disabled = !state.ready || state.busy || state.aiBusy || state.loading;
    $("create-first-world").disabled = !state.ready || state.busy || state.loading;
    $("delete-world").disabled = unavailable || state.aiBusy;
    $("filter-events").disabled = !world;
    $("show-all-people").disabled = !world;
    document.querySelectorAll("[data-intervention]").forEach((button) => {
      const livingAction = ["flood", "repair_contract"].includes(button.dataset.intervention);
      button.disabled = unavailable || (livingAction && !["city", "ferry"].includes(state.regionId));
    });
    $("open-history").hidden = !supportsHistory();
    $("open-history").disabled = unavailable;
    $("person-history").disabled = unavailable || !selectedPerson();
    const aiUnavailable = unavailable || state.aiBusy || !state.capabilities?.ai_configured;
    $("generate-chronicle").disabled = aiUnavailable;
    $("generate-chronicle").textContent = state.aiBusy ? "正在听取世界的声音…" : "为这一日写则纪事";
    const cannotSpeak = !selectedPerson() || selectedPerson().life?.health === 0;
    $("ask-npc").disabled = aiUnavailable || cannotSpeak;
    $("npc-question").disabled = aiUnavailable || cannotSpeak;
    renderPicker();
  }

  function renderMap() {
    const world = state.world;
    if (state.mapWorldId !== world.id) {
      $("map-nodes").replaceChildren();
      $("map-roads").replaceChildren();
      const roads = new Set();
      world.regions.forEach((region) => {
        const button = node("button", "map-node");
        button.id = `map-${region.id}`;
        button.style.setProperty("--x", `${region.x}%`);
        button.style.setProperty("--y", `${region.y}%`);
        const marker = node("span", "node-marker");
        marker.setAttribute("aria-hidden", "true");
        button.append(marker, node("span", "node-name", region.name), node("span", "node-detail"));
        button.addEventListener("click", () => selectRegion(region.id));
        $("map-nodes").append(button);
        region.neighbors.forEach((neighborId) => {
          const key = [region.id, neighborId].sort().join(":");
          if (roads.has(key)) return;
          roads.add(key);
          const neighbor = regionFor(neighborId);
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.id = `road-${key}`;
          line.setAttribute("x1", String(region.x * 10));
          line.setAttribute("y1", String(region.y * 6.5));
          line.setAttribute("x2", String(neighbor.x * 10));
          line.setAttribute("y2", String(neighbor.y * 6.5));
          $("map-roads").append(line);
        });
      });
      state.mapWorldId = world.id;
    }
    world.regions.forEach((region) => {
      const faction = factionFor(region.owner_id);
      const people = world.npcs.filter((person) => person.region_id === region.id
        && (!person.life || (person.life.health > 0 && !person.life.journey))).length;
      const button = $(`map-${region.id}`);
      button.style.setProperty("--faction-color", faction.color);
      button.classList.toggle("is-selected", region.id === state.regionId);
      button.setAttribute("aria-pressed", String(region.id === state.regionId));
      button.setAttribute("aria-label", `${region.name}，${faction.name}，${people}位人物。查看地点`);
      button.querySelector(".node-detail").textContent = `${faction.name}，${people}人`;
    });
    if (isLiving()) {
      const living = world.npcs.filter((person) => person.life.health > 0);
      const traveling = living.filter((person) => person.life.journey).length;
      $("map-caption").textContent = `${living.length}人存活，${traveling}人在途，历史不会随离开网页清零`;
      world.roads.forEach((road) => {
        const key = [road.origin_id, road.destination_id].sort().join(":");
        const line = $(`road-${key}`);
        const ford = road.integrity === 0 && road.ford_until_day >= world.day;
        line.setAttribute("class", road.integrity > 0 ? "" : ford ? "road-ford" : "road-blocked");
        let title = line.querySelector("title");
        if (!title) {
          title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          line.append(title);
        }
        title.textContent = `${road.name}：${road.integrity > 0 ? "正常通行" : ford ? "引流浅滩临时通行" : "已中断"}`;
      });
      const markers = living.filter((person) => person.life.journey).map((person) => {
        const journey = person.life.journey;
        const origin = regionFor(person.region_id);
        const destination = regionFor(journey.destination_id);
        const elapsed = world.running
          ? Math.min(.94, Math.max(0, (Date.now() - new Date(world.updated_at).getTime()) / (world.interval_seconds * 1000)))
          : 0;
        const fraction = journey.returning
          ? Math.max(0, (journey.remaining_days - elapsed) / journey.total_days)
          : Math.min(.98, (journey.total_days - journey.remaining_days + elapsed) / journey.total_days);
        const button = node("button", "traveler", person.name.slice(0, 1));
        button.id = `traveler-${person.id}`;
        button.style.setProperty("--x", `${origin.x + (destination.x - origin.x) * fraction}%`);
        button.style.setProperty("--y", `${origin.y + (destination.y - origin.y) * fraction}%`);
        button.dataset.focusKey = person.id;
        button.title = `${person.name}：${journeyCopy(person)}`;
        button.setAttribute("aria-label", button.title);
        button.addEventListener("click", () => selectPerson(person.id));
        return button;
      });
      replaceList($("map-travelers"), markers);
      $("map-scale-copy").textContent = "在途位置为行程估算，抵达由规则裁决";
    } else {
      $("map-caption").textContent = `${world.regions.length}处山川，${world.npcs.length}位人物，皆有自己的去处`;
      $("map-travelers").replaceChildren();
      $("map-scale-copy").textContent = "山路相连，人物沿路而行";
    }
  }

  function renderFactions() {
    $("factions").style.setProperty("--faction-count", state.world.factions.length);
    const items = state.world.factions.map((faction) => {
      const item = node("div", "faction");
      item.style.setProperty("--faction-color", faction.color);
      const territories = state.world.regions.filter((region) => region.owner_id === faction.id).length;
      item.append(
        node("p", "faction-name", faction.name),
        node("p", "faction-detail", `${territories}处驻地，${isLiving() ? "公库" : "资财"}${faction.wealth}`),
      );
      item.title = faction.philosophy;
      const influence = node("div", "faction-influence");
      const progress = document.createElement("progress");
      progress.max = 100;
      progress.value = faction.influence;
      const label = isLiving() ? "成员饱足" : "影响";
      progress.setAttribute("aria-label", `${faction.name}${label}${faction.influence}`);
      influence.append(progress, node("span", "", `${label} ${faction.influence}`));
      item.append(influence);
      return item;
    });
    $("factions").replaceChildren(...items);
  }

  function renderPlace() {
    const region = regionFor(state.regionId);
    const faction = factionFor(region.owner_id);
    $("place-title").textContent = region.name;
    $("place-terrain").textContent = region.terrain;
    $("place-description").textContent = region.description;
    $("place-owner").textContent = `${faction.name}${isLiving() ? "管理此地公共货栈" : "在此守望"}`;
    $("place-owner").style.color = faction.color;
    ["spirit", "prosperity", "danger"].forEach((key) => {
      $(`${key}-meter`).value = region[key];
      $(`${key}-value`).textContent = String(region[key]);
    });
    $("intervention-location").textContent = `当前地点：${region.name}`;
    $("place-meters").hidden = isLiving();
    $("market-section").hidden = !isLiving();
    if (isLiving()) {
      const rows = Object.entries(state.capabilities.good_names).map(([good, name]) => {
        const row = node("tr");
        const label = node("th", "", name);
        label.scope = "row";
        row.append(label, node("td", "", String(region.market.stock[good])),
          node("td", "", String(region.market.prices[good])),
          node("td", "", String(region.reserves[good])));
        return row;
      });
      $("market-stock").replaceChildren(...rows);
      $("market-cash").textContent = `货栈持有${region.market.coins}枚钱。自然产出仍需劳动收取，矿石不会再生。`;
    }
  }

  function selectPerson(personId) {
    state.personId = personId;
    renderPeople();
    renderPerson();
    renderAI();
    renderControls();
  }

  function renderPeople() {
    const people = state.world.npcs.filter((person) => state.allPeople || person.region_id === state.regionId);
    $("people-title").textContent = state.allPeople ? "山海中人" : "此地人物";
    $("show-all-people").textContent = state.allPeople ? "只看此地" : `查看所有${state.world.npcs.length}人`;
    $("show-all-people").setAttribute("aria-pressed", String(state.allPeople));
    const rows = people.map((person) => {
      const faction = factionFor(person.faction_id);
      const button = node("button", "person-row");
      button.style.setProperty("--faction-color", faction.color);
      button.classList.toggle("is-selected", person.id === state.personId);
      button.classList.toggle("is-dead", person.life?.health === 0);
      button.dataset.focusKey = person.id;
      button.setAttribute("aria-pressed", String(person.id === state.personId));
      const copy = node("span", "person-row-copy");
      const identity = node("span");
      identity.append(node("strong", "", person.name), document.createElement("br"));
      identity.append(node("small", "", `${professionFor(person)}，${journeyCopy(person)}`));
      copy.append(identity, node("span", "person-row-realm", realmFor(person)));
      button.append(node("span", "person-avatar", person.name.slice(0, 1)), copy);
      button.addEventListener("click", () => selectPerson(person.id));
      return button;
    });
    replaceList($("people-list"), rows.length ? rows : [
      node("p", "empty-copy", "此刻无人停留。可以查看所有人物，或等待下一日有人到访。"),
    ]);
  }

  function renderPerson() {
    const person = selectedPerson();
    $("person-detail").hidden = !person;
    if (!person) return;
    $("person-name").textContent = person.name;
    $("person-realm").textContent = `${realmFor(person)} / ${person.mood}`;
    $("person-goal").textContent = `${person.life ? "长期心愿" : "心愿"}：${person.goal}`;
    $("person-action").textContent = person.last_action;
    $("person-energy").textContent = `精力 ${person.energy}/100`;
    $("person-cultivation").textContent = `修行 ${person.cultivation}/100`;
    $("person-cultivation").hidden = Boolean(person.life);
    $("person-life").hidden = !person.life;
    if (!person.life) return;
    const life = person.life;
    $("person-body").textContent = `${Math.floor(life.age_days / 365)}岁，健康${life.health}/100，饥饿${life.hunger}/100`
      + (life.died_on ? `，逝于第${life.died_on}日` : "");
    $("person-inventory").textContent = `${life.health ? "随身" : "遗留"}：${goodsCopy(life.inventory)}，钱${life.coins}。`;
    $("person-journey").textContent = journeyCopy(person);
    $("person-plan").textContent = life.plan
      ? `第${life.plan.since_day}日起：${life.plan.reason}`
      : life.health ? "还没有形成新的计划。" : "生命已经结束，计划不再执行。";
    const memories = life.memories.slice(-4).reverse().map((memory) => {
      const item = node("li");
      const button = node("button", "text-button", `第${memory.day}日，查看事实 #${memory.event_id}`);
      button.addEventListener("click", () => openFact(memory.event_id));
      item.append(button, node("p", "", memory.detail));
      return item;
    });
    $("person-memories").replaceChildren(...(memories.length ? memories : [
      node("li", "", "尚无值得记下的亲历事件。"),
    ]));
    const knowledge = [];
    Object.entries(life.known_roads).forEach(([roadId, item]) => {
      if (roadId !== "river_bridge") return;
      knowledge.push(node("p", "", `关于${entityName(roadId)}：${item.passable ? "认为可通行" : "认为已中断"}；`
        + `${item.day ? `第${item.day}日` : "开局公示"}的消息，并不保证此刻仍然如此。`));
    });
    Object.entries(life.known_markets).sort((a, b) => b[1].day - a[1].day).slice(0, 4)
      .forEach(([regionId, item]) => {
        const source = item.source_id === person.id ? "亲见" : `来自${entityName(item.source_id || "旧账簿")}`;
        knowledge.push(node("p", "", `${regionFor(regionId).name}：粮价${item.prices.food}，余粮${item.stock.food}；`
          + `${item.day ? `第${item.day}日` : "开局前"}，${source}。`));
      });
    $("person-knowledge").replaceChildren(...knowledge);
    const relationships = Object.entries(life.relationships).sort((a, b) => b[1] - a[1]).slice(0, 3);
    $("person-relationships").textContent = relationships.length
      ? `共同经历留下的认可：${relationships.map(([id, value]) => `${entityName(id)} ${value > 0 ? "+" : ""}${value}`).join("，")}`
      : "";
  }

  function eventItem(event, inspect = false) {
      const item = node("li", "event-item");
      item.dataset.kind = event.kind;
      const headline = node("div", "event-headline");
      const title = node("button", "event-title", event.title);
      title.dataset.focusKey = String(event.id);
      title.disabled = !inspect && !event.region_id;
      title.addEventListener("click", () => {
        if (inspect) {
          openFact(event.id);
          return;
        }
        if (event.region_id) {
          selectRegion(event.region_id);
          if (event.npc_id) state.personId = event.npc_id;
          renderPeople();
          renderPerson();
          renderAI();
          renderControls();
        }
      });
      headline.append(node("span", "event-day", `第${event.day}日`), title);
      item.append(headline, node("p", "event-detail", event.detail));
      if (supportsHistory()) {
        const links = node("div", "event-links");
        const fact = node("button", "text-button",
          event.cause_ids?.length ? `追溯原因（${event.cause_ids.length}）` : `查看事实 #${event.id}`);
        fact.dataset.focusKey = `${event.id}-fact`;
        fact.addEventListener("click", () => openFact(event.id));
        links.append(fact);
        item.append(links);
      }
      return item;
  }

  function renderEvents() {
    const events = state.world.events.filter((event) => !state.localEvents || event.region_id === state.regionId);
    $("filter-events").textContent = state.localEvents ? "查看全世界" : "只看此地";
    $("filter-events").setAttribute("aria-pressed", String(state.localEvents));
    const items = events.slice(-16).reverse().map((event) => eventItem(event));
    replaceList($("event-list"), items.length ? items : [
      node("li", "empty-copy", "此地暂时没有见闻。推进一日，或看看其他地点。"),
    ]);
  }

  function renderLivingWorld() {
    const living = isLiving();
    document.body.dataset.ruleset = living ? "living" : "classic";
    ["living-status", "infrastructure-section", "living-interventions", "experiment-note"]
      .forEach((id) => { $(id).hidden = !living; });
    $("classic-interventions").hidden = living;
    $("intervention-title").textContent = living ? "观察实验" : "轻拨天机";
    if (!living) return;
    const world = state.world;
    const people = world.npcs.filter((person) => person.life.health > 0);
    const city = regionFor("city");
    const bridge = world.roads.find((road) => road.bridge);
    const ford = bridge.integrity === 0 && bridge.ford_until_day >= world.day;
    const condition = bridge.integrity > 0 ? "石桥可以通行" : ford ? "石桥未修复，引流浅滩暂时可渡" : "石桥中断，运输需要绕路";
    $("world-condition").textContent = `${condition}。城中货栈余粮${city.market.stock.food}份，${people.length}人仍在谋生。`;
    const season = ["春", "夏", "秋", "冬"][Math.floor((world.day - 1) / 30) % 4];
    $("river-status").textContent = `${season}季，河道水位${world.river_level}/100；库存、道路和选择彼此影响。`;
    $("ledger-status").textContent = `货币总量${world.ledger.initial_money}枚，物资来源与消耗随每次提交核对。`;
    const heading = node("h3", "", bridge.name);
    const status = node("p", "bridge-state", `完好度${bridge.integrity}/100`
      + (ford ? `，浅滩可用至第${bridge.ford_until_day}日，渡涉需${bridge.travel_days + 1}日` : ""));
    const materials = node("p", "", `工地：木材${bridge.materials.wood}/12，矿石${bridge.materials.ore}/4，已完成${bridge.repair_work}/12工日。`);
    const budget = node("p", "", `工程款余${bridge.repair_budget}枚。材料由工匠实际运入，工钱从工程款支取。`);
    const children = [heading, status, materials, budget];
    if (bridge.last_event_id) {
      const cause = node("button", "text-button", "查看这处工程最近的原因");
      cause.addEventListener("click", () => openFact(bridge.last_event_id));
      children.push(cause);
    }
    $("bridge-detail").replaceChildren(...children);
    $("road-list").replaceChildren(...world.roads.map((road) => {
      const item = node("li");
      const open = road.integrity > 0 || road.ford_until_day >= world.day;
      item.append(node("span", "", `${road.name}：${regionFor(road.origin_id).name}—${regionFor(road.destination_id).name}`),
        node("span", "", open ? `${road.travel_days + (road.integrity === 0 ? 1 : 0)}日` : "中断"));
      return item;
    }));
  }

  function resetInspection() {
    state.factRequest += 1;
    state.historyWorldId = "";
    state.historyEvents = [];
    state.historyNext = null;
    state.historyRequest += 1;
    state.historyBusy = false;
    state.pendingExperiment = null;
    ["history-dialog", "fact-dialog", "experiment-dialog"].forEach((id) => {
      if ($(id).open) $(id).close();
    });
  }

  async function openFact(eventId) {
    if (!state.world || !supportsHistory()) return;
    const worldId = state.selectedId;
    const token = ++state.factRequest;
    try {
      const event = state.world.events.find((item) => item.id === eventId)
        || state.historyEvents.find((item) => item.id === eventId)
        || await api(`/api/worlds/${worldId}/events/${eventId}`);
      if (worldId !== state.selectedId || token !== state.factRequest) return;
      $("fact-error").hidden = true;
      $("fact-title").textContent = event.title;
      $("fact-meta").textContent = `第${event.day}日，事实 #${event.id}${event.region_id ? `，${regionFor(event.region_id).name}` : ""}`;
      $("fact-detail").textContent = event.detail;
      $("fact-effects").replaceChildren(...(event.effects || []).map((effect) => {
        const fields = {
          coins: "钱", health: "健康", wealth: "公库", integrity: "完好度",
          repair_budget: "工程款", repair_work: "施工工日", research: "研究进度",
          ford_until_day: "浅滩有效期", level: "水位", profession: "职业",
          "inventory.food": "随身粮食", "inventory.wood": "随身木材", "inventory.ore": "随身矿石",
          "reserves.food": "田间粮食", "reserves.wood": "可采木材", "reserves.ore": "矿脉储量",
          "materials.wood": "工地木材", "materials.ore": "工地矿石",
        };
        return node("li", "", `${entityName(effect.subject_id)}，${fields[effect.field] || effect.field}：${effect.before} → ${effect.after}`);
      }));
      const causes = (event.cause_ids || []).map((id) => {
        const button = node("button", "text-button", `追到事实 #${id}`);
        button.addEventListener("click", () => openFact(id));
        return button;
      });
      $("fact-causes").replaceChildren(node("span", "", causes.length ? "登记的前因：" : "这条事实没有登记更早的前因。"), ...causes);
      if (!$("fact-dialog").open) $("fact-dialog").showModal();
    } catch (error) {
      if (worldId === state.selectedId) report(error);
    }
  }

  async function loadHistory() {
    if (state.historyBusy || !state.historyWorldId) return;
    const worldId = state.historyWorldId;
    const request = state.historyRequest;
    state.historyBusy = true;
    $("history-more").disabled = true;
    $("history-error").hidden = true;
    try {
      const params = new URLSearchParams({ limit: "30" });
      if (state.historyNext) params.set("before", state.historyNext);
      if (state.historyNpcId) params.set("npc_id", state.historyNpcId);
      if (state.historyRegionId) params.set("region_id", state.historyRegionId);
      const page = await api(`/api/worlds/${worldId}/events?${params}`);
      if (worldId !== state.historyWorldId || worldId !== state.selectedId || request !== state.historyRequest) return;
      state.historyEvents.push(...page.events);
      state.historyNext = page.next_before;
      $("history-list").replaceChildren(...(state.historyEvents.length
        ? state.historyEvents.map((event) => eventItem(event, true))
        : [node("li", "empty-copy", "这个范围尚无已归档的事实。")]));
      $("history-more").hidden = !page.has_more;
    } catch (error) {
      console.error(error);
      if (worldId === state.historyWorldId && request === state.historyRequest) {
        $("history-error").textContent = error.message;
        $("history-error").hidden = false;
      }
    } finally {
      if (request === state.historyRequest) {
        state.historyBusy = false;
        $("history-more").disabled = false;
      }
    }
  }

  function openHistory(personId = null) {
    if (!state.world || !supportsHistory()) return;
    state.historyRequest += 1;
    state.historyBusy = false;
    state.historyWorldId = state.selectedId;
    state.historyNpcId = personId;
    state.historyRegionId = !personId && state.localEvents ? state.regionId : null;
    state.historyEvents = [];
    state.historyNext = null;
    $("history-title").textContent = personId ? `${entityName(personId)}的行动档案` : "已发生的世界";
    $("history-description").textContent = `${state.historyRegionId ? regionFor(state.historyRegionId).name : "已归档事实"}，最新在前。`
      + "按需读取更早记录；升级前已经丢失的旧版见闻不能补回。";
    $("history-list").replaceChildren(node("li", "empty-copy", "正在查阅档案…"));
    $("history-more").hidden = true;
    if (!$("history-dialog").open) $("history-dialog").showModal();
    loadHistory();
  }

  function entryMeta(entry) {
    const tokens = entry.tokens_in + entry.tokens_out;
    return `第${entry.day}日记录，${tokens} tokens，本次估算 $${entry.cost_usd.toFixed(5)}`;
  }

  function renderAI() {
    $("ai-status").textContent = state.capabilities
      ? state.capabilities.ai_message
      : "模型配置尚未读取，AI 操作暂不可用。";
    const entries = state.world ? [...state.world.ai_entries].reverse() : [];
    const chronicle = entries.find((entry) => entry.kind === "chronicle");
    $("chronicle-meta").textContent = chronicle ? entryMeta(chronicle) : "";
    $("chronicle-text").textContent = chronicle
      ? chronicle.text
      : "点击后，AI 会根据已发生的见闻写作，不改变世界状态。";
    const person = selectedPerson();
    $("chat-label").textContent = person ? `与${person.name}对话` : "先选择一位人物";
    $("ask-npc").textContent = person ? `问一问${person.name}` : "问一问这位人物";
    const dialogue = entries.find((entry) => entry.kind === "dialogue" && entry.npc_id === person?.id);
    $("dialogue-meta").textContent = dialogue ? entryMeta(dialogue) : "";
    $("dialogue-question").textContent = dialogue ? `你问：${dialogue.question}` : "";
    $("dialogue-text").textContent = dialogue ? dialogue.text : "";
  }

  function renderWorld() {
    const world = state.world;
    if (!world) return;
    $("world-title").textContent = world.name;
    $("atlas-title").textContent = isLiving() ? "汀川舆图" : "雾海舆图";
    document.title = `${world.name} · 世界在线`;
    $("world-description").textContent = isLiving()
      ? "人物需要吃饭、运输、谋生与研究。道路会改变选择，经历会留下记忆。"
      : `${world.npcs.length}位修行者各有心愿，${world.factions.length}方势力在山川之间经营自己的日常。`;
    $("world-day").textContent = `第${world.day}日`;
    $("world-weather").textContent = world.weather;
    $("world-status").textContent = state.offline ? "连接中断" : world.running ? "正在演化" : "已暂停";
    $("world-status").dataset.state = state.offline ? "offline" : world.running ? "running" : "paused";
    $("sync-status").textContent = state.offline
      ? "连接中断，正在重试同步，后台状态暂未知"
      : world.running ? `每${world.interval_seconds}秒演化一日，网页每2秒同步` : "世界已暂停，可手动推进或开始自动演化";
    $("map-empty").hidden = true;
    $("world-error").hidden = !world.last_error;
    $("world-error").textContent = world.last_error;
    const saved = new Date(world.updated_at).toLocaleTimeString("zh-CN", { hour12: false });
    $("world-save-info").textContent = `世界种子 ${world.seed}，最近存档 ${saved}。`
      + (isLiving() ? "运行中的因果世界重启后自动继续，不补算停机时间。" : "经典世界在服务重启后暂停，等待你继续。");
    renderLivingWorld();
    renderMap();
    renderFactions();
    renderPlace();
    renderPeople();
    renderPerson();
    renderEvents();
    renderAI();
    renderControls();
  }

  function showEmpty() {
    resetInspection();
    state.world = null;
    state.selectedId = "";
    state.mapWorldId = "";
    state.regionId = "";
    state.personId = "";
    state.allPeople = false;
    state.localEvents = false;
    history.replaceState(null, "", "/world");
    document.title = "世界在线 · 山海自有去处";
    $("world-title").textContent = "山海尚未有名";
    $("atlas-title").textContent = "山海舆图";
    $("world-description").textContent = "不必成为故事的主角。先看看，这个世界自己会走向哪里。";
    $("world-day").textContent = "尚无历日";
    $("world-weather").textContent = "山川待启";
    $("world-status").textContent = "等待开辟";
    $("world-status").dataset.state = "paused";
    $("sync-status").textContent = "进度保存在当前服务器";
    $("map-empty").hidden = false;
    $("map-caption").textContent = "点选一处山川，看看谁在那里。";
    $("world-error").hidden = true;
    $("map-nodes").replaceChildren();
    $("map-roads").replaceChildren();
    $("map-travelers").replaceChildren();
    $("map-scale-copy").textContent = "山路相连，人物沿路而行";
    $("factions").replaceChildren();
    $("people-title").textContent = "此地人物";
    $("show-all-people").textContent = "查看所有人";
    $("show-all-people").setAttribute("aria-pressed", "false");
    $("people-list").replaceChildren(node("p", "empty-copy", "世界开辟后，人物将在这里相遇。"));
    $("filter-events").textContent = "只看此地";
    $("filter-events").setAttribute("aria-pressed", "false");
    $("event-list").replaceChildren(node("li", "empty-copy", "世界开辟后，第一条见闻会留在这里。"));
    $("person-detail").hidden = true;
    $("person-life").hidden = true;
    $("market-section").hidden = true;
    $("place-meters").hidden = false;
    ["living-status", "infrastructure-section", "living-interventions", "experiment-note"]
      .forEach((id) => { $(id).hidden = true; });
    $("classic-interventions").hidden = false;
    $("intervention-title").textContent = "轻拨天机";
    document.body.dataset.ruleset = "classic";
    $("place-title").textContent = "山川待访";
    $("place-terrain").textContent = "未选地点";
    $("place-description").textContent = "地图上的每一处地点，都有不同的灵气、繁荣与山路险度。";
    $("place-owner").textContent = "";
    ["spirit", "prosperity", "danger"].forEach((key) => {
      $(`${key}-meter`).value = 0;
      $(`${key}-value`).textContent = "—";
    });
    $("intervention-location").textContent = "选择地图上的地点";
    $("world-save-info").textContent = "世界由规则推进。AI 只负责你主动请求的纪事与对话。";
    renderAI();
    renderControls();
  }

  function applyWorld(world) {
    if (world.id !== state.selectedId) return;
    if (state.world?.id === world.id && world.revision < state.world.revision) return;
    if (state.world?.id !== world.id) {
      resetInspection();
      state.regionId = world.regions[0].id;
      state.personId = world.npcs.find((person) => person.region_id === state.regionId)?.id || "";
      state.preferredInterval = world.interval_seconds;
      state.allPeople = false;
      state.localEvents = false;
    } else if (world.interval_seconds !== state.world.interval_seconds && !state.busy) {
      state.preferredInterval = world.interval_seconds;
    }
    state.world = world;
    state.offline = false;
    updateSummary(world);
    history.replaceState(null, "", `/world#${world.id}`);
    renderWorld();
  }

  function selectRegion(regionId) {
    if (!state.world || state.loading) return;
    state.regionId = regionId;
    state.personId = state.world.npcs.find((person) => person.region_id === regionId)?.id || "";
    state.allPeople = false;
    renderWorld();
  }

  async function chooseWorld(id) {
    const token = ++state.selectionToken;
    state.loading = true;
    state.selectedId = id;
    renderControls();
    try {
      const world = await api(`/api/worlds/${id}`);
      if (token === state.selectionToken) applyWorld(world);
    } catch (error) {
      if (token === state.selectionToken) {
        state.selectedId = state.world?.id || "";
        report(error);
      }
    } finally {
      if (token === state.selectionToken) {
        state.loading = false;
        renderControls();
      }
    }
  }

  async function perform(suffix, body, message) {
    if (!state.world || state.busy || state.loading) return;
    const id = state.selectedId;
    state.busy = true;
    renderControls();
    try {
      const world = await api(`/api/worlds/${id}/${suffix}`, { method: "POST", body });
      applyWorld(world);
      announce(message || `世界已推进至第${world.day}日`);
    } catch (error) {
      report(error);
    } finally {
      state.busy = false;
      renderControls();
    }
  }

  async function syncWorld() {
    if (!state.world || state.loading || state.polling || document.hidden) return;
    const id = state.selectedId;
    state.polling = true;
    try {
      const world = await api(`/api/worlds/${id}`);
      if (id === state.selectedId) applyWorld(world);
    } catch (error) {
      if (id === state.selectedId) {
        if (error instanceof APIError && error.status === 404) {
          state.summaries = state.summaries.filter((world) => world.id !== id);
          showEmpty();
          report(error);
        } else {
          if (!state.offline) report(error);
          state.offline = true;
          renderWorld();
        }
      }
    } finally {
      state.polling = false;
    }
  }

  function openCreate() {
    $("create-error").hidden = true;
    $("create-dialog").showModal();
    $("new-world-name").focus();
    $("new-world-name").select();
  }

  function updateRulesetCopy() {
    const living = $("new-world-ruleset").value === "living";
    $("ruleset-description").textContent = living
      ? "七处地点、三十个人、两股组织。从真实口粮、断桥与公共工程开始，研究能够改变水路的力量。"
      : "六处山川、九位修行者。保留原来的旅行、修炼、经商与势力规则，不改动已有世界。";
    if (["汀川·初生", "雾海九州"].includes($("new-world-name").value)) {
      $("new-world-name").value = living ? "汀川·初生" : "雾海九州";
    }
  }

  async function createWorld(event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    $("submit-create").disabled = true;
    $("submit-create").textContent = "山海正在初开…";
    $("create-error").hidden = true;
    renderControls();
    const seed = $("new-world-seed").value.trim();
    try {
      const body = { name: $("new-world-name").value.trim(), seed: seed ? Number(seed) : null };
      if (Array.isArray(state.capabilities.rulesets)) body.ruleset = $("new-world-ruleset").value;
      const world = await api("/api/worlds", {
        method: "POST",
        body,
      });
      state.selectedId = world.id;
      applyWorld(world);
      $("create-dialog").close();
      announce(`${world.name}已经开辟，当前为暂停状态`);
    } catch (error) {
      console.error(error);
      $("create-error").textContent = error instanceof Error ? error.message : "创建世界失败，请查看服务日志。";
      $("create-error").hidden = false;
    } finally {
      state.busy = false;
      $("submit-create").disabled = false;
      $("submit-create").textContent = "开辟世界";
      renderControls();
    }
  }

  async function askAI(kind) {
    if (!state.world || state.aiBusy || !state.capabilities.ai_configured) return;
    const person = selectedPerson();
    if (kind === "chat" && (!person || person.life?.health === 0)) return;
    state.aiBusy = true;
    renderControls();
    try {
      const options = { method: "POST" };
      if (kind === "chat") options.body = { npc_id: person.id, question: $("npc-question").value.trim() };
      const world = await api(`/api/worlds/${state.selectedId}/${kind}`, options);
      applyWorld(world);
      announce(kind === "chat" ? `${person.name}的回答已保存` : "这一天的纪事已保存");
    } catch (error) {
      report(error);
    } finally {
      state.aiBusy = false;
      renderControls();
    }
  }

  async function deleteWorld() {
    if (!state.world || state.busy || state.aiBusy) return;
    const id = state.selectedId;
    state.busy = true;
    $("confirm-delete").disabled = true;
    renderControls();
    try {
      await api(`/api/worlds/${id}`, { method: "DELETE" });
      state.summaries = state.summaries.filter((world) => world.id !== id);
      $("delete-dialog").close();
      showEmpty();
      if (state.summaries.length) await chooseWorld(state.summaries[0].id);
      announce("世界存档已删除");
    } catch (error) {
      $("delete-dialog").close();
      report(error);
    } finally {
      state.busy = false;
      $("confirm-delete").disabled = false;
      renderControls();
    }
  }

  $("new-world").addEventListener("click", openCreate);
  $("create-first-world").addEventListener("click", openCreate);
  $("close-create").addEventListener("click", () => $("create-dialog").close());
  $("create-form").addEventListener("submit", createWorld);
  $("new-world-ruleset").addEventListener("change", updateRulesetCopy);
  $("world-select").addEventListener("change", (event) => chooseWorld(event.target.value));
  $("dismiss-notice").addEventListener("click", () => { $("notice").hidden = true; });
  $("run-world").addEventListener("click", () => perform("control", {
    action: state.world.running ? "pause" : "start", interval_seconds: state.preferredInterval,
  }, state.world.running ? "世界已暂停" : "世界开始自动演化"));
  $("step-world").addEventListener("click", () => perform("control", { action: "step" }));
  $("world-speed").addEventListener("change", (event) => {
    state.preferredInterval = Number(event.target.value);
    if (state.world.running) perform("control", { action: "start", interval_seconds: state.preferredInterval }, "世界流速已更新");
  });
  document.querySelectorAll("[data-intervention]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.intervention;
      if (isLiving()) {
        state.pendingExperiment = { kind, region_id: state.regionId };
        $("experiment-title").textContent = kind === "flood" ? "向石桥施加洪水扰动？" : "从公库追加修桥委托？";
        $("experiment-description").textContent = kind === "flood"
          ? "会把水位推至95并冲击石桥、冲散临时浅滩。在途人物可能折返或受伤，商路与生计可能随之变化。记录会明确标记这是观察者实验。"
          : "从汀川议事会的现有公库划拨40枚钱进入石桥工程款。不会生成新钱，也不会强迫工匠施工；公库不足或桥梁无需重建时会拒绝。";
        $("experiment-dialog").showModal();
        return;
      }
      perform("intervene", { kind, region_id: state.regionId }, "干预已记录在山海见闻中");
    });
  });
  ["close-experiment", "cancel-experiment"].forEach((id) => {
    $(id).addEventListener("click", () => {
      state.pendingExperiment = null;
      $("experiment-dialog").close();
    });
  });
  $("confirm-experiment").addEventListener("click", () => {
    const experiment = state.pendingExperiment;
    if (!experiment) return;
    state.pendingExperiment = null;
    $("experiment-dialog").close();
    perform("intervene", experiment, "观察实验已记录，人物将自行作出应对");
  });
  $("open-history").addEventListener("click", () => openHistory());
  $("person-history").addEventListener("click", () => openHistory(state.personId));
  $("history-more").addEventListener("click", loadHistory);
  $("close-history").addEventListener("click", () => {
    state.historyRequest += 1;
    state.historyBusy = false;
    state.historyWorldId = "";
    $("history-dialog").close();
  });
  $("close-fact").addEventListener("click", () => {
    state.factRequest += 1;
    $("fact-dialog").close();
  });
  $("fact-dialog").addEventListener("close", () => { state.factRequest += 1; });
  $("history-dialog").addEventListener("close", () => {
    state.historyRequest += 1;
    state.historyBusy = false;
    state.historyWorldId = "";
  });
  $("experiment-dialog").addEventListener("close", () => { state.pendingExperiment = null; });
  $("show-all-people").addEventListener("click", () => {
    state.allPeople = !state.allPeople;
    renderPeople();
  });
  $("filter-events").addEventListener("click", () => {
    state.localEvents = !state.localEvents;
    renderEvents();
  });
  $("locate-person").addEventListener("click", () => {
    const person = selectedPerson();
    if (!person) return;
    state.regionId = person.region_id;
    state.allPeople = false;
    renderWorld();
    const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
    $("atlas-frame").scrollIntoView({ behavior, block: "center" });
    const target = person.life?.journey ? $(`traveler-${person.id}`) : $(`map-${person.region_id}`);
    target.focus({ preventScroll: true });
  });
  $("generate-chronicle").addEventListener("click", () => askAI("chronicle"));
  $("chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    askAI("chat");
  });
  $("delete-world").addEventListener("click", () => {
    $("delete-description").textContent = `你正在删除《${state.world.name}》第${state.world.day}日的世界存档。`;
    $("delete-dialog").showModal();
  });
  ["close-delete", "cancel-delete"].forEach((id) => {
    $(id).addEventListener("click", () => $("delete-dialog").close());
  });
  $("confirm-delete").addEventListener("click", deleteWorld);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) syncWorld();
  });

  async function boot() {
    const [capabilities, worlds] = await Promise.all([
      api("/api/worlds/capabilities"), api("/api/worlds"),
    ]);
    state.capabilities = capabilities;
    const rulesets = capabilities.rulesets || ["classic"];
    [...$("new-world-ruleset").options].forEach((option) => {
      option.disabled = !rulesets.includes(option.value);
    });
    if (!rulesets.includes($("new-world-ruleset").value)) $("new-world-ruleset").value = "classic";
    updateRulesetCopy();
    state.summaries = worlds;
    state.ready = true;
    renderAI();
    renderPicker();
    if (worlds.length) {
      const bookmarked = location.hash.slice(1);
      const selected = worlds.find((world) => world.id === bookmarked) || worlds[0];
      await chooseWorld(selected.id);
    } else {
      showEmpty();
    }
  }

  renderControls();
  boot().catch(report);
  setInterval(syncWorld, 2000);
})();
