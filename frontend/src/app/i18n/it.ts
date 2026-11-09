/**
 * Italian UI texts, keyed by the English text (see core/i18n.ts). `scripts/check-i18n.mjs` fails when a
 * marked text has no entry here. Terms kept in English on purpose (common in Italian IT usage): workspace,
 * notebook, chunk, embedding, rerank, OCR, Workbench, Wiki.
 */
export const IT: Readonly<Record<string, string>> = {
  // model phases
  Chat: 'Chat',
  'Summary & suggested questions': 'Riassunto e domande suggerite',
  'Graph extraction': 'Estrazione del grafo',
  'Image description': 'Descrizione delle immagini',
  OCR: 'OCR',
  Embedding: 'Embedding',
  Rerank: 'Rerank',

  // shell
  'OpenNotebook home': 'Home di OpenNotebook',
  Main: 'Principale',
  Theme: 'Tema',
  'Choose theme': 'Scegli il tema',
  Language: 'Lingua',
  'Choose language': 'Scegli la lingua',
  'Account menu': 'Menu account',
  'Sign out': 'Esci',
  Workbench: 'Workbench',
  Upload: 'Carica',
  Wiki: 'Wiki',
  'RAG Status': 'Stato RAG',
  Settings: 'Impostazioni',
  System: 'Sistema',
  Light: 'Chiaro',
  Dark: 'Scuro',

  // login
  'Sign in to continue': 'Accedi per continuare',
  or: 'oppure',
  Email: 'Email',
  Password: 'Password',
  'Sign in': 'Accedi',

  // groups
  'Share a project, workspace or notebook with a group (Share… in the Workbench): every member gets the role, on that node and everything inside it. Groups marked SSO are kept in sync with the identity provider at each sign-in.':
    'Condividi un progetto, un workspace o un notebook con un gruppo (Condividi… nel Workbench): ogni membro riceve il ruolo su quel nodo e su tutto ciò che contiene. I gruppi contrassegnati SSO sono sincronizzati con l’identity provider a ogni accesso.',
  'New group': 'Nuovo gruppo',
  Description: 'Descrizione',
  Create: 'Crea',
  'Synchronized from single sign-on': 'Sincronizzato dal single sign-on',
  Members: 'Membri',
  'No groups yet.': 'Nessun gruppo.',
  'Delete group (its grants are removed)': 'Elimina il gruppo (i suoi accessi vengono rimossi)',
  'Delete group': 'Elimina il gruppo',
  'Add a member': 'Aggiungi un membro',
  'Remove member': 'Rimuovi il membro',
  'No members.': 'Nessun membro.',
  'Group created': 'Gruppo creato',
  'Delete group “{name}”? Access granted to the group is removed.':
    'Eliminare il gruppo “{name}”? Gli accessi concessi al gruppo vengono rimossi.',
  'Group deleted': 'Gruppo eliminato',
  Close: 'Chiudi',

  // models
  Configure: 'Configura',
  'Global defaults (all projects)': 'Impostazioni globali (tutti i progetti)',
  'Project: {name}': 'Progetto: {name}',
  'A project override replaces the global chain for this project only. Empty override = use global defaults.':
    'Una configurazione di progetto sostituisce la catena globale solo per questo progetto. Configurazione vuota = usa le impostazioni globali.',
  'Defaults used by every project without its own override.':
    'Impostazioni usate da ogni progetto senza una configurazione propria.',
  'Read only: project owners can change this configuration.':
    'Sola lettura: solo i proprietari del progetto possono cambiare questa configurazione.',
  'Read only: administrators can change this configuration.':
    'Sola lettura: solo gli amministratori possono cambiare questa configurazione.',
  'Using project override': 'Configurazione di progetto',
  'Using global default': 'Impostazione globale',
  Configured: 'Configurato',
  'Not configured': 'Non configurato',
  'dim {n}': 'dim {n}',
  'No longer listed by the provider': 'Non più elencato dal provider',
  unavailable: 'non disponibile',
  'Move up': 'Sposta su',
  'Move down': 'Sposta giù',
  Remove: 'Rimuovi',
  'No override: the global chain applies.':
    'Nessuna configurazione propria: vale la catena globale.',
  'No model selected.': 'Nessun modello selezionato.',
  'Add fallback model': 'Aggiungi un modello di riserva',
  'Select model': 'Seleziona un modello',
  'No enabled model with this capability (Settings → Providers)':
    'Nessun modello abilitato con questa capacità (Impostazioni → Provider)',
  'Sources already indexed with another embedding model must be re-indexed.':
    'Le fonti già indicizzate con un altro modello di embedding vanno re-indicizzate.',
  Discard: 'Annulla modifiche',
  Save: 'Salva',
  'Answers in the Workbench. Users can pick any enabled chat model; this chain is the default and the fallback order.':
    'Risposte nel Workbench. Gli utenti possono scegliere qualsiasi modello di chat abilitato; questa catena è il default e l’ordine di riserva.',
  'Source summaries and suggested questions generated after ingestion.':
    'Riassunti delle fonti e domande suggerite, generati dopo l’indicizzazione.',
  'Entity and relation extraction for the knowledge graph.':
    'Estrazione di entità e relazioni per il knowledge graph.',
  'Descriptions of images and figures.': 'Descrizioni di immagini e figure.',
  'Text extraction from images and scanned pages (OCR models or vision models).':
    'Estrazione del testo da immagini e pagine scansionate (modelli OCR o di visione).',
  'Vectors for semantic search. One model per index, no fallback: changing it requires re-indexing.':
    'Vettori per la ricerca semantica. Un modello per indice, senza riserva: cambiarlo richiede la re-indicizzazione.',
  'Optional re-ordering of retrieved passages. Leave empty to disable.':
    'Riordino facoltativo dei passaggi trovati. Lascia vuoto per disattivarlo.',
  '{phase} saved': '{phase}: salvato',

  // providers
  Providers: 'Provider',
  'Add provider': 'Aggiungi provider',
  'No model runs inside OpenNotebook: every model call goes to one of these external providers. Keys are stored encrypted and never shown again.':
    'Nessun modello gira dentro OpenNotebook: ogni chiamata va a uno di questi provider esterni. Le chiavi sono salvate cifrate e non vengono più mostrate.',
  Provider: 'Provider',
  Name: 'Nome',
  'lowercase, used in MODEL_* settings': 'minuscolo, usato nelle impostazioni MODEL_*',
  'API key': 'Chiave API',
  'Base URL': 'URL di base',
  'Timeout (s)': 'Timeout (s)',
  'Add and sync models': 'Aggiungi e sincronizza i modelli',
  Key: 'Chiave',
  Models: 'Modelli',
  '{n} enabled / {total}': '{n} abilitati / {total}',
  'Last sync': 'Ultima sincronizzazione',
  error: 'errore',
  Enabled: 'Abilitato',
  'Enable {name}': 'Abilita {name}',
  'Sync model catalog': 'Sincronizza il catalogo dei modelli',
  Sync: 'Sincronizza',
  'No providers yet. Keys present in .env are imported at first start.':
    'Nessun provider. Le chiavi presenti in .env vengono importate al primo avvio.',
  'Replace API key': 'Sostituisci la chiave API',
  'Save key': 'Salva la chiave',
  'Search models': 'Cerca modelli',
  Capability: 'Capacità',
  Any: 'Tutte',
  'Enabled only': 'Solo abilitati',
  Use: 'Uso',
  Model: 'Modello',
  'Not listed by the provider anymore, or retired': 'Non più elencato dal provider, o dismesso',
  Capabilities: 'Capacità',
  'Set manually': 'Impostate a mano',
  'Detected ({how}); click to override': 'Rilevate ({how}); clicca per modificarle',
  'Context / dim': 'Contesto / dim',
  Test: 'Prova',
  'testing…': 'prova in corso…',
  'No models. Use Sync or add one manually below.':
    'Nessun modello. Usa Sincronizza o aggiungine uno a mano qui sotto.',
  'Add model manually': 'Aggiungi un modello a mano',
  'e.g. BAAI/bge-m3': 'es. BAAI/bge-m3',
  Add: 'Aggiungi',
  'Provider added': 'Provider aggiunto',
  '{name}: {n} models ({added} new, {gone} no longer listed)':
    '{name}: {n} modelli ({added} nuovi, {gone} non più elencati)',
  Disabled: 'Disabilitato',
  'API key updated': 'Chiave API aggiornata',
  'Remove provider “{name}” and its model catalog?':
    'Rimuovere il provider “{name}” e il suo catalogo di modelli?',
  'Provider removed': 'Provider rimosso',
  'Model added': 'Modello aggiunto',

  // settings, users
  'Settings sections': 'Sezioni delle impostazioni',
  Users: 'Utenti',
  Groups: 'Gruppi',
  'Access to projects, workspaces and notebooks is granted from the Workbench tree (node menu → Share).':
    'L’accesso a progetti, workspace e notebook si concede dall’albero del Workbench (menu del nodo → Condividi).',
  'Display name': 'Nome visualizzato',
  'Initial password': 'Password iniziale',
  'at least 12 characters': 'almeno 12 caratteri',
  Administrator: 'Amministratore',
  'Create user': 'Crea utente',
  Admin: 'Admin',
  Active: 'Attivo',
  'User created': 'Utente creato',

  // RAG status
  'Version {v}': 'Versione {v}',
  Refresh: 'Aggiorna',
  Services: 'Servizi',
  'Sources by status': 'Fonti per stato',
  'Queues:': 'Code:',
  'Index by project': 'Indice per progetto',
  Project: 'Progetto',
  'Embedding model': 'Modello di embedding',
  'project override': 'configurazione di progetto',
  'searches still served by': 'ricerche ancora servite da',
  'until every source is re-indexed': 'finché ogni fonte non è re-indicizzata',
  Sources: 'Fonti',
  Chunks: 'Chunk',
  'Needs re-index': 'Da re-indicizzare',
  'Indexed with a different embedding model than the current one':
    'Indicizzate con un modello di embedding diverso da quello attuale',
  'Re-index': 'Re-indicizza',
  'Rebuild graph': 'Ricostruisci il grafo',
  'No projects.': 'Nessun progetto.',
  'Failed sources': 'Fonti non riuscite',
  Retry: 'Riprova',
  'Recent jobs': 'Job recenti',
  Started: 'Avviato',
  Reason: 'Motivo',
  Result: 'Esito',
  '(attempt {n})': '(tentativo {n})',
  'No jobs yet.': 'Nessun job.',
  'Re-index every source of “{name}”? This calls the embedding provider for all chunks.':
    'Re-indicizzare tutte le fonti di “{name}”? Il provider di embedding viene chiamato per tutti i chunk.',
  '{n} sources queued': '{n} fonti in coda',
  'Re-extract the knowledge graph of “{name}”? Documents are sent again to the graph extraction model (code needs no model).':
    'Ri-estrarre il knowledge graph di “{name}”? I documenti vengono inviati di nuovo al modello di estrazione del grafo (il codice non richiede modelli).',
  '{n} sources queued for graph extraction': '{n} fonti in coda per l’estrazione del grafo',

  // upload
  'Upload sources': 'Carica fonti',
  'Upload to (project, workspace or notebook)': 'Carica in (progetto, workspace o notebook)',
  'Nothing you can upload to: ask for editor access':
    'Non hai nodi in cui caricare: chiedi l’accesso come editor',
  'Drop documents, source code, images or archives here':
    'Trascina qui documenti, codice sorgente, immagini o archivi',
  'Choose files': 'Scegli i file',
  'PDF (scanned pages via OCR), DOCX, Markdown, text, HTML · code (C, C++, Python, JS/TS, Java, Go, Rust, C#, PHP, Ruby, shell and more) · PNG, JPEG, WebP, TIFF, GIF (OCR + description) · ZIP and TAR archives (each file becomes a source)':
    'PDF (pagine scansionate via OCR), DOCX, Markdown, testo, HTML · codice (C, C++, Python, JS/TS, Java, Go, Rust, C#, PHP, Ruby, shell e altri) · PNG, JPEG, WebP, TIFF, GIF (OCR + descrizione) · archivi ZIP e TAR (ogni file diventa una fonte)',
  'Add web pages': 'Aggiungi pagine web',
  'URLs (one per line)': 'URL (uno per riga)',
  'Follow links': 'Segui i link',
  'No, only these pages': 'No, solo queste pagine',
  '1 level, same site': '1 livello, stesso sito',
  '2 levels, same site': '2 livelli, stesso sito',
  'Max pages': 'Pagine massime',
  'Add 1 page': 'Aggiungi 1 pagina',
  'Add {n} pages': 'Aggiungi {n} pagine',
  'Add pages': 'Aggiungi pagine',
  'Pages are fetched by the server: main text only (menus and footers removed), robots.txt is respected when following links, and private network addresses are refused.':
    'Le pagine vengono scaricate dal server: solo il testo principale (menu e piè di pagina rimossi), robots.txt viene rispettato quando si seguono i link e gli indirizzi di reti private vengono rifiutati.',
  '{name}: already in this notebook': '{name}: già presente in questo notebook',
  '{name}: queued for indexing': '{name}: in coda per l’indicizzazione',
  'Sources here and inside': 'Fonti qui e nei nodi interni',
  Source: 'Fonte',
  Size: 'Dimensione',
  Status: 'Stato',
  Added: 'Aggiunta',
  'No sources yet.': 'Nessuna fonte.',

  // wiki
  Scope: 'Ambito',
  'Find an entity': 'Cerca un’entità',
  Entities: 'Entità',
  Mentions: 'Menzioni',
  'No entities yet. They are extracted after indexing when a graph extraction model is configured (Settings → Models); source code needs no model.':
    'Nessuna entità. Vengono estratte dopo l’indicizzazione se è configurato un modello di estrazione del grafo (Impostazioni → Modelli); il codice sorgente non richiede modelli.',
  View: 'Vista',
  Graph: 'Grafo',
  Page: 'Pagina',
  '{n} entities in scope': '{n} entità nell’ambito',
  'Nothing to show in this scope yet.': 'Ancora niente da mostrare in questo ambito.',
  'Knowledge graph': 'Knowledge graph',
  '{name} ({type}, {n} mentions)': '{name} ({type}, {n} menzioni)',
  mention: 'menzione',
  mentions: 'menzioni',
  'also: {names}': 'anche: {names}',
  'Rewrite the page': 'Riscrivi la pagina',
  'Writing the page from the passages you can read…':
    'Scrittura della pagina dai passaggi che puoi leggere…',
  'Written by {model}': 'Scritta da {model}',
  '· only from sources you can read': '· solo da fonti che puoi leggere',
  Related: 'Correlate',
  'Mentioned in': 'Citata in',

  // answers and chat
  'Open source {n}: {title}': 'Apri la fonte {n}: {title}',
  Conversation: 'Conversazione',
  'New chat': 'Nuova chat',
  'Conversation actions': 'Azioni sulla conversazione',
  Rename: 'Rinomina',
  Delete: 'Elimina',
  'Select a project, workspace or notebook in the tree to chat with its sources.':
    'Seleziona un progetto, un workspace o un notebook nell’albero per chattare con le sue fonti.',
  'Ask a question about the active sources in this scope.':
    'Fai una domanda sulle fonti attive in questo ambito.',
  'Answers use only these sources, and every statement links to the passage it comes from.':
    'Le risposte usano solo queste fonti e ogni affermazione rimanda al passaggio da cui proviene.',
  'Research report · {steps} search steps, {passages} passages':
    'Report di ricerca · {steps} passi di ricerca, {passages} passaggi',
  Stopped: 'Interrotta',
  'Found through the knowledge graph': 'Trovato tramite il knowledge graph',
  fallback: 'riserva',
  Copy: 'Copia',
  'Copy answer': 'Copia la risposta',
  'Save as note in {name}': 'Salva come nota in {name}',
  'Save as note': 'Salva come nota',
  'Ask the sources in scope': 'Chiedi alle fonti dell’ambito',
  'Select a scope first': 'Prima seleziona un ambito',
  'Plan sub-questions, search each one and write a structured report with citations (slower)':
    'Pianifica sotto-domande, cerca ciascuna e scrive un report strutturato con citazioni (più lento)',
  'Deep research': 'Ricerca approfondita',
  Stop: 'Ferma',
  Ask: 'Chiedi',
  'Delete this conversation?': 'Eliminare questa conversazione?',
  'Chat answer': 'Risposta della chat',
  'Saved as note': 'Salvata come nota',
  Copied: 'Copiato',
  'Copy is not available in this browser context':
    'La copia non è disponibile in questo contesto del browser',
  'Planning the research…': 'Pianificazione della ricerca…',
  'Searching {n} of {of}: {question}': 'Ricerca {n} di {of}: {question}',
  'Searching…': 'Ricerca in corso…',
  'Searching the sources…': 'Ricerca nelle fonti…',
  'Reading {n} passages…': 'Lettura di {n} passaggi…',
  '1 sentence has no citation': '1 frase non ha citazioni',
  '{n} sentences have no citation': '{n} frasi non hanno citazioni',
  'Removed citations to passages that were not provided: {list}':
    'Rimosse le citazioni a passaggi non forniti: {list}',
  '{model}: failed ({error})': '{model}: non riuscito ({error})',
  '{model}: answered': '{model}: ha risposto',

  // dialogs
  Cancel: 'Annulla',
  'Share “{name}”': 'Condividi “{name}”',
  'Access granted here also applies to everything inside this {kind}.':
    'L’accesso concesso qui vale anche per tutto ciò che contiene questo {kind}.',
  'Remove access': 'Rimuovi l’accesso',
  'No direct grants on this node.': 'Nessun accesso diretto su questo nodo.',
  'Person or group': 'Persona o gruppo',
  Role: 'Ruolo',
  Viewer: 'Lettore',
  Editor: 'Editor',
  Owner: 'Proprietario',

  // notes
  'Select a notebook to see and write its notes.':
    'Seleziona un notebook per vedere e scrivere le sue note.',
  'New note': 'Nuova nota',
  Title: 'Titolo',
  'Note (Markdown)': 'Nota (Markdown)',
  'Index as source (searchable)': 'Indicizza come fonte (ricercabile)',
  'Index status: {status}': 'Stato dell’indice: {status}',
  'Edit note': 'Modifica la nota',
  'Delete note': 'Elimina la nota',
  'No notes in this notebook yet.': 'Nessuna nota in questo notebook.',
  'Delete note “{title}”?': 'Eliminare la nota “{title}”?',

  // project settings
  'Project settings · {name}': 'Impostazioni del progetto · {name}',
  'Provider policy': 'Policy dei provider',
  'Which model providers may receive this project’s content (documents, questions, images). It applies to every model call: chat, embeddings, OCR, summaries, graph, wiki.':
    'Quali provider di modelli possono ricevere i contenuti di questo progetto (documenti, domande, immagini). Vale per ogni chiamata ai modelli: chat, embedding, OCR, riassunti, grafo, wiki.',
  'All configured providers': 'Tutti i provider configurati',
  'Only the selected providers': 'Solo i provider selezionati',
  'No provider selected: nothing can be indexed or answered in this project.':
    'Nessun provider selezionato: in questo progetto non si può indicizzare né rispondere.',
  'Only project owners can change the policy.':
    'Solo i proprietari del progetto possono cambiare la policy.',
  'Search index': 'Indice di ricerca',
  'Serving searches:': 'Serve le ricerche:',
  'Configured embedding model:': 'Modello di embedding configurato:',
  '{done} / {total} sources re-indexed with the new model. Searches keep using the current index until all are done, then switch at once. Start or continue with RAG Status → Re-index.':
    '{done} / {total} fonti re-indicizzate con il nuovo modello. Le ricerche usano l’indice attuale finché non sono tutte pronte, poi passano al nuovo in un colpo solo. Avvia o continua da Stato RAG → Re-indicizza.',
  'Last index switch: {date}': 'Ultimo cambio di indice: {date}',
  'Save policy': 'Salva la policy',

  // search panel
  'No passages found in the active sources of this scope.':
    'Nessun passaggio trovato nelle fonti attive di questo ambito.',
  'Search the active sources in the selected scope.':
    'Cerca nelle fonti attive dell’ambito selezionato.',
  'The same hybrid retrieval feeds the chat: use it to check which passages a question finds.':
    'La stessa ricerca ibrida alimenta la chat: usala per vedere quali passaggi trova una domanda.',
  'Embedding model: {model}': 'Modello di embedding: {model}',
  'Search the sources in scope': 'Cerca nelle fonti dell’ambito',
  'Select a scope in the tree first': 'Prima seleziona un ambito nell’albero',
  Search: 'Cerca',

  // source details and viewer
  '(shown as PDF)': '(mostrato come PDF)',
  '{n} pages': '{n} pagine',
  '{n} chunk': '{n} chunk',
  '{n} chunks': '{n} chunk',
  'indexed {date}': 'indicizzata il {date}',
  'Download original': 'Scarica l’originale',
  'Delete source': 'Elimina la fonte',
  '(retrying automatically)': '(nuovo tentativo automatico)',
  'fetched {date}': 'scaricata il {date}',
  '{n} linked pages added': '{n} pagine collegate aggiunte',
  Summary: 'Riassunto',
  'Ask in the chat': 'Chiedi nella chat',
  'Summary being generated…': 'Riassunto in preparazione…',
  'No summary: {error}': 'Nessun riassunto: {error}',
  Archive: 'Archivio',
  '1 file indexed as a source': '1 file indicizzato come fonte',
  '{n} files indexed as sources': '{n} file indicizzati come fonti',
  '{n} skipped': '{n} saltati',
  '{size} uncompressed': '{size} non compressi',
  'Skipped files': 'File saltati',
  'lines {start}–{end}': 'righe {start}–{end}',
  '{n} tokens': '{n} token',
  'No chunks.': 'Nessun chunk.',
  'Load more': 'Carica altri',
  'Delete “{title}”? Its chunks and vectors are removed too.':
    'Eliminare “{title}”? Vengono rimossi anche i suoi chunk e vettori.',
  'Source deleted': 'Fonte eliminata',
  'Back to the chat': 'Torna alla chat',
  Back: 'Indietro',
  'Previous page': 'Pagina precedente',
  'Next page': 'Pagina successiva',
  'Source details': 'Dettagli della fonte',
  'Could not open the source: {error}': 'Impossibile aprire la fonte: {error}',

  // tree and workbench
  project: 'progetto',
  workspace: 'workspace',
  notebook: 'notebook',
  'New project': 'Nuovo progetto',
  'New workspace': 'Nuovo workspace',
  'New notebook': 'Nuovo notebook',
  'Upload to this {kind}': 'Carica in questo {kind}',
  Collapse: 'Comprimi',
  'Collapse sources': 'Comprimi le fonti',
  'No projects yet. Create one to start organizing sources.':
    'Nessun progetto. Creane uno per iniziare a organizzare le fonti.',
  'Loading…': 'Caricamento…',
  'Toggle {name}': 'Espandi o comprimi {name}',
  'Included in search': 'Inclusa nella ricerca',
  'Excluded from search': 'Esclusa dalla ricerca',
  'Include {name} in search': 'Includi {name} nella ricerca',
  'Node actions': 'Azioni sul nodo',
  'Project settings…': 'Impostazioni del progetto…',
  'Share…': 'Condividi…',
  'Show sources': 'Mostra le fonti',
  'Center panel': 'Pannello centrale',
  'Select a project, workspace or notebook to set the scope':
    'Seleziona un progetto, un workspace o un notebook per impostare l’ambito',
  'Chat model': 'Modello di chat',
  '· default': '· predefinito',
  'Show notes': 'Mostra le note',
  Notes: 'Note',
  'Collapse notes': 'Comprimi le note',
  'Project name': 'Nome del progetto',
  'Project created': 'Progetto creato',
  '{what} in “{parent}”': '{what} in “{parent}”',
  'Created: {name}': 'Creato: {name}',
  'Rename {kind}': 'Rinomina {kind}',
  Renamed: 'Rinominato',
  'Enabled for search': 'Incluso nella ricerca',
  'Excluded from search (including everything inside)':
    'Escluso dalla ricerca (con tutto ciò che contiene)',
  'Source included in search': 'Fonte inclusa nella ricerca',
  'Source excluded from search': 'Fonte esclusa dalla ricerca',
  'Delete “{name}” and everything inside it, including its sources?':
    'Eliminare “{name}” e tutto ciò che contiene, comprese le fonti?',
  Deleted: 'Eliminato',

  // server messages
  'Invalid email or password': 'Email o password non validi',
  'Too many login attempts, retry later': 'Troppi tentativi di accesso, riprova più tardi',
  'User disabled': 'Utente disabilitato',
  'Password sign-in is disabled: use single sign-on':
    'L’accesso con password è disattivato: usa il single sign-on',
  'Too many questions: wait a minute and retry': 'Troppe domande: attendi un minuto e riprova',
  'Too many searches: wait a minute and retry': 'Troppe ricerche: attendi un minuto e riprova',
  'Deep research limit reached for this hour': 'Limite orario di ricerche approfondite raggiunto',
  'A sibling with the same name already exists':
    'Esiste già un elemento con lo stesso nome allo stesso livello',
  'A project must keep at least one owner': 'Un progetto deve avere almeno un proprietario',
  'Administrator role required': 'Serve il ruolo di amministratore',
  'Ingestion already in progress': 'Indicizzazione già in corso',
  'The server cannot be reached. Check the connection and retry.':
    'Il server non è raggiungibile. Controlla la connessione e riprova.',

  // source and job statuses
  queued: 'in coda',
  parsing: 'analisi',
  chunking: 'suddivisione',
  embedding: 'embedding',
  ready: 'pronta',
  failed: 'non riuscita',
  pending: 'in attesa',
  running: 'in corso',
};
