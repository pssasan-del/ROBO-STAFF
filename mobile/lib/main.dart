import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'services/api_service.dart';
import 'king_bro_theme.dart';

void main() => runApp(const NeoSignalApp());

class NeoSignalApp extends StatefulWidget {
  const NeoSignalApp({super.key});
  @override State<NeoSignalApp> createState() => _NeoSignalAppState();
}

class _NeoSignalAppState extends State<NeoSignalApp> {
  String baseUrl = 'http://129.154.35.105:8080';
  bool ready = false;
  @override void initState(){super.initState();_load();}
  Future<void> _load() async {final p=await SharedPreferences.getInstance();if(!mounted)return;setState((){baseUrl=p.getString('api')??baseUrl;ready=true;});}
  Future<void> _save(String v) async {final p=await SharedPreferences.getInstance();await p.setString('api',v);if(mounted)setState(()=>baseUrl=v);}
  @override Widget build(BuildContext context){
    return MaterialApp(
      debugShowCheckedModeBanner:false,
      title:'NEO Signal',
      theme:KingBroTheme.theme,
      home:ready?TerminalShell(baseUrl:baseUrl,onBaseUrl:_save):const Scaffold(body:Center(child:CircularProgressIndicator())),
    );
  }}

class TerminalShell extends StatefulWidget {
  const TerminalShell({super.key,required this.baseUrl,required this.onBaseUrl});
  final String baseUrl; final ValueChanged<String> onBaseUrl;
  @override State<TerminalShell> createState()=>_TerminalShellState();
}
class _TerminalShellState extends State<TerminalShell>{
  int index=0; late ApiService api; StreamSubscription? tickSub; bool ws=false; Map<String,dynamic> lastTick={};
  @override void initState(){super.initState();api=ApiService(widget.baseUrl);_connect();}
  @override void didUpdateWidget(covariant TerminalShell old){super.didUpdateWidget(old);if(old.baseUrl!=widget.baseUrl){api=ApiService(widget.baseUrl);_connect();setState((){});}}
  void _connect(){tickSub?.cancel();tickSub=api.reconnectingTicks().listen((m){if(!mounted)return;if(m['_connection']=='connected'){setState(()=>ws=true);}else if(m['_connection']=='disconnected'){setState(()=>ws=false);}else{setState(()=>lastTick=m);}});}
  @override void dispose(){tickSub?.cancel();super.dispose();}
  @override Widget build(BuildContext context){final pages=[HomePage(api:api,ws:ws,lastTick:lastTick),SignalsPage(api:api),ScannerPage(api:api),TradePage(api:api),PortfolioPage(api:api),MorePage(api:api,initialUrl:widget.baseUrl,onUrl:widget.onBaseUrl,ws:ws)];return Scaffold(body:SafeArea(child:IndexedStack(index:index,children:pages)),bottomNavigationBar:NavigationBar(selectedIndex:index,onDestinationSelected:(v)=>setState(()=>index=v),destinations:const [NavigationDestination(icon:Icon(Icons.home_outlined),selectedIcon:Icon(Icons.home),label:'Home'),NavigationDestination(icon:Icon(Icons.bolt_outlined),selectedIcon:Icon(Icons.bolt),label:'Signals'),NavigationDestination(icon:Icon(Icons.radar),selectedIcon:Icon(Icons.radar),label:'Scanner'),NavigationDestination(icon:Icon(Icons.swap_horiz),label:'Trade'),NavigationDestination(icon:Icon(Icons.pie_chart_outline),selectedIcon:Icon(Icons.pie_chart),label:'Portfolio'),NavigationDestination(icon:Icon(Icons.grid_view_outlined),selectedIcon:Icon(Icons.grid_view),label:'More')]));}
}

class PageFrame extends StatelessWidget{
  const PageFrame({super.key,required this.title,required this.child,this.actions=const []});
  final String title; final Widget child; final List<Widget> actions;
  @override Widget build(BuildContext context)=>RefreshIndicator(
    onRefresh:()async{},
    child:Stack(children:[
      const Positioned.fill(child:DecoratedBox(decoration:BoxDecoration(gradient:KbColors.backgroundGradient))),
      const Positioned.fill(child:IgnorePointer(child:CustomPaint(painter:RobotGridPainter()))),
      CustomScrollView(
        physics:const AlwaysScrollableScrollPhysics(),
        slivers:[
          SliverAppBar(
            backgroundColor:KbColors.bgTop.withValues(alpha:.92),
            surfaceTintColor:Colors.transparent,
            floating:true,
            title:Row(children:[
              Container(width:10,height:10,decoration:const BoxDecoration(shape:BoxShape.circle,color:KbColors.cyan,boxShadow:[BoxShadow(color:Color(0x9900E5FF),blurRadius:14,spreadRadius:1)])),
              const SizedBox(width:10),
              Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
                Text(title,style:const TextStyle(fontWeight:FontWeight.w900,letterSpacing:.4,color:KbColors.text)),
                const Text('KING BRO // NEO CORE',style:TextStyle(fontSize:8,letterSpacing:1.6,fontWeight:FontWeight.w800,color:KbColors.textMuted)),
              ])),
            ]),
            actions:actions,
          ),
          SliverPadding(padding:const EdgeInsets.fromLTRB(16,4,16,30),sliver:SliverToBoxAdapter(child:child)),
        ],
      ),
    ]),
  );
}

class RobotGridPainter extends CustomPainter{
  const RobotGridPainter();
  @override void paint(Canvas canvas,Size size){
    final fine=Paint()..color=const Color(0x1200CFFF)..strokeWidth=.6;
    final major=Paint()..color=const Color(0x1D00A8FF)..strokeWidth=.8;
    const step=28.0;
    for(double x=0;x<size.width;x+=step){canvas.drawLine(Offset(x,0),Offset(x,size.height),((x/step).round()%4==0)?major:fine);}
    for(double y=0;y<size.height;y+=step){canvas.drawLine(Offset(0,y),Offset(size.width,y),((y/step).round()%4==0)?major:fine);}
    final glow=Paint()..shader=const RadialGradient(colors:[Color(0x2600E5FF),Color(0x0000E5FF)]).createShader(Rect.fromCircle(center:Offset(size.width*.82,size.height*.12),radius:size.width*.6));
    canvas.drawRect(Offset.zero&size,glow);
  }
  @override bool shouldRepaint(covariant CustomPainter oldDelegate)=>false;
}

class HomePage extends StatefulWidget{const HomePage({super.key,required this.api,required this.ws,required this.lastTick});final ApiService api;final bool ws;final Map<String,dynamic> lastTick;@override State<HomePage>createState()=>_HomePageState();}
class _HomePageState extends State<HomePage>{Map<String,dynamic> boot={};String? error;Timer? timer;@override void initState(){super.initState();_load();timer=Timer.periodic(const Duration(seconds:5),(_)=>_load(silent:true));}@override void dispose(){timer?.cancel();super.dispose();}
 Future<void>_load({bool silent=false})async{try{final r=await widget.api.getJson('/app/bootstrap');if(mounted)setState((){boot=r;error=null;});}catch(e){if(mounted&&!silent)setState(()=>error='$e');}}
 @override Widget build(BuildContext context){
   final health=_map(boot['health']);
   final sum=_map(boot['position_summary']);
   final ex=_map(boot['execution']);
   final risk=_map(boot['risk']);
   final scanner=_map(boot['scanner']);
   final stats=_map(boot['signal_stats']);
   final signals=(boot['signals'] as List?)??[];
   final mtm=_num(sum['day_mtm']);
   final open=_int(sum['open_positions']);
   final indices=(boot['indices'] as List?)??[];
   final latest=signals.isNotEmpty?_map(signals.first):<String,dynamic>{};
   final scanActive=scanner['active']==true;
   return PageFrame(
     title:'KING BRO TRADE',
     actions:[Padding(padding:const EdgeInsets.only(right:12),child:StatusPill(ok:widget.ws&&health['market_feed_stale']!=true,label:widget.ws?'LIVE':'RECONNECT'))],
     child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
       if(error!=null)Notice(error!),
       if(indices.isNotEmpty)IndexStrip(items:indices)else const EmptyState(icon:Icons.sensors,text:'Connecting NIFTY • BANKNIFTY • SENSEX'),
       const SizedBox(height:10),
       RobotPanel(glow:false,padding:const EdgeInsets.symmetric(horizontal:12,vertical:12),child:Row(children:[
         Expanded(child:_HomeMetric(label:'DAY P&L',value:_money(mtm,sign:true),accent:mtm>=0?KbColors.emerald:KbColors.coral)),
         const _HudDivider(),
         Expanded(child:_HomeMetric(label:'POSITIONS',value:'$open',accent:KbColors.cyan)),
         const _HudDivider(),
         Expanded(child:_HomeMetric(label:'SCANNER',value:scanActive?'${scanner['group']??'-'} • ${scanner['ready_count']??0}/${max(1,_int(scanner['resolved_count']))}':'OFF',accent:scanActive?KbColors.cyan:KbColors.textMuted)),
       ])),
       const SizedBox(height:10),
       Row(children:[
         Expanded(child:_CompactState(icon:Icons.cloud_done_outlined,label:'KOTAK',value:health['authenticated']==true?'CONNECTED':'LOGIN',ok:health['authenticated']==true)),
         const SizedBox(width:7),
         Expanded(child:_CompactState(icon:Icons.stream,label:'FEED',value:health['market_stream_running']==true?'RUNNING':'OFFLINE',ok:health['market_stream_running']==true)),
         const SizedBox(width:7),
         Expanded(child:_CompactState(icon:ex['armed']==true?Icons.lock_open:Icons.lock_outline,label:'EXEC',value:ex['armed']==true?'ARMED':'SAFE',ok:ex['armed']==true)),
       ]),
       if(latest.isNotEmpty)...[
         const SizedBox(height:14),
         Row(children:[const Expanded(child:SectionTitle('LATEST SIGNAL')),Text('${stats['live']??0} LIVE',style:const TextStyle(fontSize:10,fontWeight:FontWeight.w900,color:KbColors.cyan))]),
         const SizedBox(height:7),SignalCard(latest,onTap:(){}),
       ]else...[
         const SizedBox(height:14),
         RobotPanel(glow:false,padding:const EdgeInsets.all(13),child:Row(children:[const Icon(Icons.radar,color:KbColors.cyan),const SizedBox(width:10),Expanded(child:Text(scanActive?'Group ${scanner['group']} • ${scanner['resolved_count']??0} live • ${scanner['ready_count']??0} ready • ${scanner['warming_count']??0} warming':'Scanner standby • choose A or B from Scanner',style:const TextStyle(fontSize:12,fontWeight:FontWeight.w700,color:KbColors.textSecondary)))])),
       ],
       const SizedBox(height:12),
       Text(risk['trading_enabled']==true?'RISK GATE ON • protected live execution':'RISK GATE OFF • analysis mode',textAlign:TextAlign.center,style:TextStyle(fontSize:9,letterSpacing:.8,fontWeight:FontWeight.w800,color:risk['trading_enabled']==true?KbColors.amber:KbColors.textMuted)),
     ]),
   );
 }

}

class SignalsPage extends StatefulWidget{const SignalsPage({super.key,required this.api});final ApiService api;@override State<SignalsPage>createState()=>_SignalsPageState();}
class _SignalsPageState extends State<SignalsPage>{List<dynamic> items=[];Map<String,dynamic> stats={};String? error;bool busy=false;@override void initState(){super.initState();_load();}
 Future<void>_load()async{setState(()=>busy=true);try{final v=await Future.wait([widget.api.getAny('/signals/lifecycle'),widget.api.getJson('/signals/stats')]);if(mounted)setState((){items=v[0] is List?v[0] as List:[];stats=_map(v[1]);error=null;});}catch(e){if(mounted)setState(()=>error='$e');}finally{if(mounted)setState(()=>busy=false);}}
 void _open(Map<String,dynamic>x){showModalBottomSheet(context:context,isScrollControlled:true,showDragHandle:true,builder:(c)=>SignalSheet(api:widget.api,signal:x));}
 @override Widget build(BuildContext context)=>PageFrame(title:'Signals',actions:[IconButton(onPressed:busy?null:_load,icon:const Icon(Icons.refresh))],child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[RobotPanel(child:Row(children:[Expanded(child:_MiniMetric(label:'LIVE',value:'${stats['live']??0}',icon:Icons.bolt)),Expanded(child:_MiniMetric(label:'T1+',value:'${stats['wins']??0}',icon:Icons.trending_up)),Expanded(child:_MiniMetric(label:'SL',value:'${stats['losses']??0}',icon:Icons.shield_outlined)),Expanded(child:_MiniMetric(label:'AVG SCORE',value:'${stats['avg_score']??'-'}',icon:Icons.speed))])),const SizedBox(height:12),if(error!=null)Notice(error!),if(items.isEmpty&&!busy)const EmptyState(icon:Icons.bolt_outlined,text:'Signal engine scanning • no qualified setup yet'),...items.map((v){final x=_map(v);return Padding(padding:const EdgeInsets.only(bottom:10),child:SignalCard(x,onTap:()=>_open(x)));})]));}


class ScannerPage extends StatefulWidget{
  const ScannerPage({super.key,required this.api});
  final ApiService api;
  @override State<ScannerPage> createState()=>_ScannerPageState();
}
class _ScannerPageState extends State<ScannerPage>{
  String mode='IDLE';
  String note='90-stock universe • run only the group you select';
  bool busy=false;
  int resolved=0, failed=0, ready=0, warming=0;
  @override void initState(){super.initState();_status();}
  Future<void> _status() async {
    try{final r=await widget.api.getJson('/scanner/status');if(!mounted)return;setState((){final active=r['active']==true;mode=active?'GROUP ${r['group']}':'IDLE';resolved=_int(r['resolved_count']);failed=_int(r['failed_count']);ready=_int(r['ready_count']);warming=_int(r['warming_count']);note=active?'$resolved live • $ready strategy-ready • $warming warming':'90-stock universe • run only the group you select';});}catch(_){ }
  }
  Future<void> _start(String group) async {
    setState((){busy=true;note='Resolving and subscribing Group $group…';});
    try{final r=await widget.api.postJson('/scanner/start',{'group':group});if(!mounted)return;setState((){mode='GROUP ${r['group']??group}';resolved=_int(r['resolved_count']);failed=_int(r['failed_count']);ready=_int(r['ready_count']);warming=_int(r['warming_count']);note='$resolved live • $ready strategy-ready • $warming warming';});}catch(e){if(mounted)setState(()=>note='Scanner start failed: $e');}finally{if(mounted)setState(()=>busy=false);}
  }
  Future<void> _stop() async {
    setState((){busy=true;note='Stopping scanner…';});
    try{await widget.api.postJson('/scanner/stop',{});if(mounted)setState((){mode='IDLE';resolved=0;failed=0;ready=0;warming=0;note='Scanner stopped • market index feed remains available';});}catch(e){if(mounted)setState(()=>note='Scanner stop failed: $e');}finally{if(mounted)setState(()=>busy=false);}
  }
  @override Widget build(BuildContext context)=>PageFrame(
    title:'AI Scanner',
    actions:[IconButton(onPressed:busy?null:_status,icon:const Icon(Icons.refresh))],
    child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
        Row(children:[
          Container(width:48,height:48,decoration:BoxDecoration(shape:BoxShape.circle,border:Border.all(color:const Color(0xff25d8ff)),boxShadow:const [BoxShadow(color:Color(0x5500d8ff),blurRadius:18)]),child:Icon(busy?Icons.sync:Icons.radar,color:const Color(0xff35dcff))),
          const SizedBox(width:12),
          Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
            const Text('KOTAK NEO SIGNAL RADAR',style:TextStyle(fontSize:11,letterSpacing:1.3,fontWeight:FontWeight.w900,color:Color(0xff35dcff))),
            const SizedBox(height:4),
            Text(mode,style:const TextStyle(fontSize:22,fontWeight:FontWeight.w900,color:Color(0xffe6fbff))),
          ])),
          if(mode!='IDLE') StatusPill(ok:ready>0,label:'$ready READY'),
        ]),
        const SizedBox(height:14),
        Text(note,style:const TextStyle(color:Color(0xff91adbd),fontWeight:FontWeight.w700)),
        if(mode!='IDLE')...[const SizedBox(height:12),Row(children:[Expanded(child:_MiniMetric(label:'RESOLVED',value:'$resolved',icon:Icons.link)),Expanded(child:_MiniMetric(label:'READY',value:'$ready',icon:Icons.verified_outlined)),Expanded(child:_MiniMetric(label:'WARMING',value:'$warming',icon:Icons.hourglass_bottom)),Expanded(child:_MiniMetric(label:'SKIPPED',value:'$failed',icon:Icons.remove_circle_outline))])],
        const SizedBox(height:14),
        const Wrap(spacing:7,runSpacing:7,children:[
          RobotChip(icon:Icons.timer_outlined,label:'5M STRICT',active:true),
          RobotChip(icon:Icons.show_chart,label:'EMA 9/21',active:true),
          RobotChip(icon:Icons.bolt,label:'BREAKOUT',active:true),
          RobotChip(icon:Icons.speed,label:'RSI',active:true),
          RobotChip(icon:Icons.insights,label:'WILLIAMS %R',active:true),
          RobotChip(icon:Icons.security,label:'R:R ≥ 1.85',active:true),
        ]),
      ])),
      const SizedBox(height:16),
      Row(children:[
        Expanded(child:FilledButton.icon(onPressed:busy?null:()=>_start('A'),icon:const Icon(Icons.play_arrow),label:const Text('START A • 45'))),
        const SizedBox(width:10),
        Expanded(child:FilledButton.icon(onPressed:busy?null:()=>_start('B'),icon:const Icon(Icons.play_arrow),label:const Text('START B • 45'))),
      ]),
      const SizedBox(height:10),
      OutlinedButton.icon(onPressed:busy?null:_stop,icon:const Icon(Icons.stop_circle_outlined),label:const Text('STOP SCAN')),
      const SizedBox(height:18),
      Notice(mode=='IDLE'?'Scanner is OFF. Start A or B; only that 45-stock batch will consume scanner subscriptions.':'Group ${mode.replaceFirst('GROUP ','')} is actively connected to the Oracle scanner backend.'),
    ]),
  );
}

class SignalSheet extends StatelessWidget{
  const SignalSheet({super.key,required this.api,required this.signal});
  final ApiService api;
  final Map<String,dynamic> signal;
  @override Widget build(BuildContext context){
    final state='${signal['state']??'ACTIVE'}';
    final executable=(signal['trading_symbol']??signal['tradingSymbol']??'').toString().trim().isNotEmpty;
    return SafeArea(child:SingleChildScrollView(child:Padding(padding:const EdgeInsets.fromLTRB(20,4,20,24),child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Row(children:[Expanded(child:Text('${signal['symbol_key']??signal['symbol']??'Signal'}',style:Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight:FontWeight.w900,color:KbColors.text))),Chip(label:Text(state))]),
      const SizedBox(height:14),
      MetricGrid(items:[('Entry',signal['entry']),('Stop',signal['stop']??signal['stop_loss']),('T1',signal['target1']),('T2',signal['target2']),('T3',signal['target3']),('Side',signal['side']),('R:R',signal['rr']),('Score',signal['score']),('RSI 14',signal['rsi14']),('Williams %R',signal['williams_r14']),('TF','${_int(signal['timeframe_sec'])~/60}M'),('Last',signal['last_price'])]),
      if('${signal['reason']??''}'.isNotEmpty)...[const SizedBox(height:14),RobotPanel(glow:false,child:Text('${signal['reason']}',style:const TextStyle(color:KbColors.textSecondary,fontWeight:FontWeight.w700)))],
      const SizedBox(height:16),
      FilledButton.icon(onPressed:executable?()=>showDialog(context:context,barrierDismissible:false,builder:(c)=>SignalTradeDialog(api:api,signal:signal)):null,icon:const Icon(Icons.bolt),label:const Text('TRADE THIS SIGNAL')),
      const SizedBox(height:8),
      Text(executable?'Signal values prefill the protected execution ticket. You still confirm before any live order.':'This signal has no broker trading_symbol, so direct execution is disabled. Use Manual Trade after selecting the exact Kotak instrument.',style:const TextStyle(color:KbColors.textMuted)),
    ]))));
  }
}

class SignalTradeDialog extends StatefulWidget{
  const SignalTradeDialog({super.key,required this.api,required this.signal});
  final ApiService api; final Map<String,dynamic> signal;
  @override State<SignalTradeDialog> createState()=>_SignalTradeDialogState();
}
class _SignalTradeDialogState extends State<SignalTradeDialog>{
  final qty=TextEditingController(text:'1');
  String product='MIS'; bool busy=false; String? message;
  @override void dispose(){qty.dispose();super.dispose();}
  Future<void>_prepare()async{
    final s=widget.signal; final q=int.tryParse(qty.text.trim())??0;
    final ts='${s['trading_symbol']??s['tradingSymbol']??''}'.trim();
    final side='${s['side']??'BUY'}'.toUpperCase();
    final ref=_num(s['last_price']??s['entry']);
    if(q<=0||ts.isEmpty||ref<=0){setState(()=>message='Quantity, broker trading symbol and signal price are required.');return;}
    setState((){busy=true;message='Running risk gate…';});
    try{
      final intent=await widget.api.postJson('/execution/intent',{
        'exchange_segment':'${s['exchange_segment']??'nse_cm'}','product':product,'price':'0','order_type':'MKT','quantity':q,'validity':'DAY','trading_symbol':ts,
        'transaction_type':side=='SELL'||side=='SHORT'?'S':'B','trigger_price':'0','amo':'NO','disclosed_quantity':'0','reference_price':ref,'live_price':ref,'open_positions':0,'day_pnl':0.0,
      });
      if(intent['ok']!=true)throw Exception('Blocked: ${intent['reasons']}');
      if(!mounted)return;
      Navigator.of(context).pop();
      await showDialog(context:context,barrierDismissible:false,builder:(c)=>ConfirmTradeDialog(api:widget.api,intent:intent,livePrice:ref));
    }catch(e){if(mounted)setState(()=>message='$e');}
    finally{if(mounted)setState(()=>busy=false);}
  }
  @override Widget build(BuildContext context){final s=widget.signal;final side='${s['side']??'BUY'}'.toUpperCase();return AlertDialog(title:const Text('Protected Signal Trade'),content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    Text('${s['trading_symbol']??s['tradingSymbol']??s['symbol_key']??'-'}',style:const TextStyle(fontWeight:FontWeight.w900)),const SizedBox(height:8),
    Text('$side • Entry ${s['entry']??'-'} • SL ${s['stop']??s['stop_loss']??'-'} • T1 ${s['target1']??'-'}',style:const TextStyle(color:KbColors.textMuted)),const SizedBox(height:12),
    TextField(controller:qty,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Quantity')),const SizedBox(height:10),
    DropdownButtonFormField<String>(value:product,items:const [DropdownMenuItem(value:'MIS',child:Text('MIS')),DropdownMenuItem(value:'CNC',child:Text('CNC')),DropdownMenuItem(value:'NRML',child:Text('NRML'))],onChanged:(v)=>setState(()=>product=v??product),decoration:const InputDecoration(labelText:'Product')),
    if(message!=null)...[const SizedBox(height:10),Notice(message!)],
  ])),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton.icon(onPressed:busy?null:_prepare,icon:const Icon(Icons.shield_outlined),label:Text(busy?'CHECKING…':'RISK CHECK'))]);}
}

class TradePage extends StatefulWidget{
  const TradePage({super.key,required this.api});
  final ApiService api;
  @override State<TradePage>createState()=>_TradePageState();
}

class _TradePageState extends State<TradePage>{
  int tab=0;
  @override Widget build(BuildContext context)=>PageFrame(
    title:'Trade Desk',
    child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
        const Text('KING BRO EXECUTION DESK',style:TextStyle(fontSize:11,letterSpacing:1.3,fontWeight:FontWeight.w900,color:KbColors.cyan)),
        const SizedBox(height:5),
        const Text('ORDER TERMINAL',style:TextStyle(fontSize:18,fontWeight:FontWeight.w900,letterSpacing:.8,color:KbColors.text)),
        const SizedBox(height:10),
        const Text('Manual • Options • Orders  //  protected execution',style:TextStyle(fontSize:11,color:KbColors.textMuted)),
      ])),
      const SizedBox(height:14),
      SegmentedButton<int>(
        segments:const [
          ButtonSegment(value:0,icon:Icon(Icons.candlestick_chart),label:Text('Manual')),
          ButtonSegment(value:1,icon:Icon(Icons.stacked_line_chart),label:Text('Options')),
          ButtonSegment(value:2,icon:Icon(Icons.receipt_long),label:Text('Orders')),
        ],
        selected:{tab},
        onSelectionChanged:(v)=>setState(()=>tab=v.first),
      ),
      const SizedBox(height:16),
      if(tab==0) ManualTradePanel(api:widget.api),
      if(tab==1) OptionTradePanel(api:widget.api),
      if(tab==2) OrdersPanel(api:widget.api),
    ]),
  );
}

class ManualTradePanel extends StatefulWidget{
  const ManualTradePanel({super.key,required this.api});
  final ApiService api;
  @override State<ManualTradePanel>createState()=>_ManualTradePanelState();
}
class _ManualTradePanelState extends State<ManualTradePanel>{
  final symbol=TextEditingController();
  final qty=TextEditingController(text:'1');
  final limitPrice=TextEditingController(text:'0');
  final trigger=TextEditingController(text:'0');
  final reference=TextEditingController();
  String segment='nse_cm',side='BUY',product='MIS',orderType='MKT';
  List<Map<String,dynamic>> results=[];
  Map<String,dynamic>? selected;
  double livePrice=0;
  bool busy=false,quoteBusy=false;
  String? message;

  @override void dispose(){for(final c in [symbol,qty,limitPrice,trigger,reference]){c.dispose();}super.dispose();}

  Future<void>_search()async{
    if(symbol.text.trim().isEmpty)return;
    setState((){busy=true;message='Searching Kotak instruments…';results=[];selected=null;livePrice=0;});
    try{
      final raw=await widget.api.postAny('/instruments/search',{'exchange_segment':segment,'symbol':symbol.text.trim().toUpperCase()});
      final preferred=(raw is Map && raw['normalized'] is List) ? (raw['normalized'] as List).map(_map).toList() : _collectInstrumentRows(raw).toList();
      final rows=_dedupeInstrumentRows(preferred).take(12).toList();
      if(!mounted)return;
      setState((){results=rows;message=rows.isEmpty?'No matching instrument returned by Kotak.':'${rows.length} matches • select the exact contract';});
    }catch(e){if(mounted)setState(()=>message='Search failed: $e');}
    finally{if(mounted)setState(()=>busy=false);}
  }

  Future<void>_select(Map<String,dynamic>x)async{
    final token='${x['instrument_token']??x['instrumentToken']??x['token']??x['pSymbol']??x['p_symbol']??''}';
    final seg='${x['exchange_segment']??x['exchangeSegment']??segment}';
    setState((){selected=x;segment=seg;message=null;livePrice=0;quoteBusy=true;});
    if(token.isEmpty){setState((){message='Kotak did not return a tradable token for this row.';quoteBusy=false;});return;}
    try{
      final q=await widget.api.getAny('/market/quote',query:{'exchange_segment':seg,'instrument_token':token,'quote_type':'all'});
      final p=_extractMarketPrice(q);
      if(!mounted)return;
      setState((){livePrice=p;if(p>0)reference.text=p.toStringAsFixed(2);message=p>0?null:'Live quote has no usable LTP; enter reference LTP manually.';});
    }catch(e){if(mounted)setState(()=>message='Live quote unavailable. You can still enter the reference LTP manually.');}
    finally{if(mounted)setState(()=>quoteBusy=false);}
  }

  Future<void>_prepare()async{
    final x=selected;
    if(x==null){setState(()=>message='Search and select an instrument first.');return;}
    final q=int.tryParse(qty.text.trim())??0;
    final ref=livePrice>0?livePrice:_double(reference.text);
    if(q<=0||ref<=0){setState(()=>message='Valid quantity and live/reference price required.');return;}
    final ts='${x['trading_symbol']??x['tradingSymbol']??x['symbol']??x['pTrdSymbol']??x['p_trd_symbol']??symbol.text.trim().toUpperCase()}';
    if(ts.isEmpty){setState(()=>message='Trading symbol missing in selected instrument.');return;}
    setState((){busy=true;message='Running risk checks…';});
    try{
      final intent=await widget.api.postJson('/execution/intent',{
        'exchange_segment':segment,
        'product':product,
        'price':orderType=='MKT'?'0':limitPrice.text.trim(),
        'order_type':orderType,
        'quantity':q,
        'validity':'DAY',
        'trading_symbol':ts,
        'transaction_type':side=='BUY'?'B':'S',
        'trigger_price':trigger.text.trim().isEmpty?'0':trigger.text.trim(),
        'amo':'NO','disclosed_quantity':'0',
        'reference_price':ref,'live_price':livePrice>0?livePrice:ref,
        'open_positions':0,'day_pnl':0.0,
      });
      if(intent['ok']!=true){throw Exception('Blocked: ${intent['reasons']}');}
      if(!mounted)return;
      await showDialog(context:context,barrierDismissible:false,builder:(c)=>ConfirmTradeDialog(api:widget.api,intent:intent,livePrice:livePrice>0?livePrice:ref));
      if(mounted)setState(()=>message='Execution request completed. Check Orders for broker status.');
    }catch(e){if(mounted)setState(()=>message='$e');}
    finally{if(mounted)setState(()=>busy=false);}
  }

  @override Widget build(BuildContext context)=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Row(children:[
        Expanded(flex:2,child:TextField(controller:symbol,textCapitalization:TextCapitalization.characters,decoration:const InputDecoration(labelText:'Search symbol',hintText:'RELIANCE / INFY / SBIN'))),
        const SizedBox(width:8),
        Expanded(child:DropdownButtonFormField<String>(value:segment,items:const [
          DropdownMenuItem(value:'nse_cm',child:Text('NSE')),
          DropdownMenuItem(value:'bse_cm',child:Text('BSE')),
          DropdownMenuItem(value:'nse_fo',child:Text('NFO')),
          DropdownMenuItem(value:'bse_fo',child:Text('BFO')),
        ],onChanged:(v)=>setState(()=>segment=v??segment),decoration:const InputDecoration(labelText:'Segment'))),
      ]),
      const SizedBox(height:10),
      FilledButton.icon(onPressed:busy?null:_search,icon:const Icon(Icons.search),label:Text(busy?'SEARCHING…':'FIND INSTRUMENT')),
    ])),
    if(message!=null)Padding(padding:const EdgeInsets.only(top:10),child:Notice(message!)),
    if(results.isNotEmpty)...[
      const SizedBox(height:14),
      const SectionTitle('MATCHING INSTRUMENTS'),const SizedBox(height:8),
      ...results.map((x)=>Padding(padding:const EdgeInsets.only(bottom:7),child:InstrumentCandidateTile(x:x,selected:identical(selected,x),onTap:()=>_select(x)))),
    ],
    if(selected!=null)...[
      const SizedBox(height:14),
      RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
        Row(children:[Expanded(child:Text(_instrumentLabel(selected!),style:const TextStyle(fontSize:18,fontWeight:FontWeight.w900,color:KbColors.text))),if(quoteBusy)const SizedBox(width:18,height:18,child:CircularProgressIndicator(strokeWidth:2))else if(livePrice>0)Text('\u20B9${livePrice.toStringAsFixed(2)}',style:const TextStyle(fontSize:20,fontWeight:FontWeight.w900,color:KbColors.emerald))]),
        const SizedBox(height:12),
        SegmentedButton<String>(segments:const [ButtonSegment(value:'BUY',label:Text('BUY')),ButtonSegment(value:'SELL',label:Text('SELL'))],selected:{side},onSelectionChanged:(v)=>setState(()=>side=v.first)),
        const SizedBox(height:10),
        Row(children:[
          Expanded(child:DropdownButtonFormField<String>(value:product,items:const [DropdownMenuItem(value:'MIS',child:Text('MIS')),DropdownMenuItem(value:'CNC',child:Text('CNC')),DropdownMenuItem(value:'NRML',child:Text('NRML'))],onChanged:(v)=>setState(()=>product=v??product),decoration:const InputDecoration(labelText:'Product'))),
          const SizedBox(width:8),
          Expanded(child:DropdownButtonFormField<String>(value:orderType,items:const [DropdownMenuItem(value:'MKT',child:Text('Market')),DropdownMenuItem(value:'L',child:Text('Limit')),DropdownMenuItem(value:'SL',child:Text('SL')),DropdownMenuItem(value:'SL-M',child:Text('SL-M'))],onChanged:(v)=>setState(()=>orderType=v??orderType),decoration:const InputDecoration(labelText:'Order type'))),
        ]),
        const SizedBox(height:10),
        Row(children:[Expanded(child:TextField(controller:qty,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Quantity'))),const SizedBox(width:8),Expanded(child:TextField(controller:reference,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Reference LTP')))]),
        if(orderType!='MKT')...[const SizedBox(height:10),TextField(controller:limitPrice,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Limit price'))],
        if(orderType=='SL'||orderType=='SL-M')...[const SizedBox(height:10),TextField(controller:trigger,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Trigger price'))],
        const SizedBox(height:14),
        SwipeGuard(label:'SWIPE TO PREPARE $side',onTriggered:_prepare),
      ])),
    ],
  ]);
}

class InstrumentCandidateTile extends StatelessWidget{
  const InstrumentCandidateTile({super.key,required this.x,required this.selected,required this.onTap});
  final Map<String,dynamic>x;final bool selected;final VoidCallback onTap;
  @override Widget build(BuildContext context){
    final seg='${x['exchange_segment']??x['exchangeSegment']??x['segment']??'NSE'}'.toUpperCase();
    final token='${x['instrument_token']??x['instrumentToken']??x['token']??x['pSymbol']??x['p_symbol']??''}';
    final kind='${x['instrument_type']??x['instrumentType']??x['type']??'EQUITY'}'.toUpperCase();
    return RobotPanel(onTap:onTap,highlight:selected,child:Row(children:[
      Icon(selected?Icons.radio_button_checked:Icons.radio_button_off,color:selected?KbColors.cyan:KbColors.textMuted),const SizedBox(width:10),
      Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text(_instrumentLabel(x),style:const TextStyle(fontWeight:FontWeight.w900,color:KbColors.text)),const SizedBox(height:4),
        Wrap(spacing:6,runSpacing:4,children:[_MetaTag(seg),_MetaTag(kind),if(token.isNotEmpty)_MetaTag('ID ${token.length>8?token.substring(token.length-8):token}')]),
      ])),
      const Icon(Icons.chevron_right,color:KbColors.textMuted),
    ]));
  }
}

class _MetaTag extends StatelessWidget{const _MetaTag(this.text);final String text;@override Widget build(BuildContext context)=>Container(padding:const EdgeInsets.symmetric(horizontal:7,vertical:3),decoration:BoxDecoration(color:KbColors.cardSoft,borderRadius:BorderRadius.circular(7),border:Border.all(color:KbColors.border)),child:Text(text,style:const TextStyle(fontSize:8,fontWeight:FontWeight.w800,color:KbColors.textMuted)));}

class OptionTradePanel extends StatefulWidget{const OptionTradePanel({super.key,required this.api});final ApiService api;@override State<OptionTradePanel>createState()=>_OptionTradePanelState();}
class _OptionTradePanelState extends State<OptionTradePanel>{
  final underlying=TextEditingController(text:'NIFTY');final expiry=TextEditingController();final ltp=TextEditingController();final step=TextEditingController(text:'50');final qty=TextEditingController(text:'75');
  String type='CE';String product='MIS';Map<String,dynamic>? selected;List<dynamic> candidates=[];bool busy=false;String? message;
  @override void dispose(){for(final c in [underlying,expiry,ltp,step,qty]){c.dispose();}super.dispose();}
  Future<void>_scan()async{final u=_double(ltp.text),s=_double(step.text);if(u<=0||s<=0||expiry.text.trim().isEmpty){setState(()=>message='Enter expiry, underlying LTP and strike step.');return;}setState((){busy=true;message=null;});try{final r=await widget.api.postJson('/options/scan',{'underlying':underlying.text.trim().toUpperCase(),'expiry':expiry.text.trim(),'option_type':type,'underlying_ltp':u,'strike_step':s,'strikes_each_side':3,'exchange_segment':'NSEFO'});if(mounted)setState((){candidates=(r['candidates'] as List?)??[];selected=r['selected'] is Map?_map(r['selected']):null;message=selected==null?'No option passed quality filters.':'Best contract selected from live broker quotes.';});}catch(e){if(mounted)setState(()=>message='$e');}finally{if(mounted)setState(()=>busy=false);}}
  Future<void>_prepare()async{final x=selected;if(x==null)return;final q=int.tryParse(qty.text)??0;final price=_num(x['ltp']);if(q<=0||price<=0){setState(()=>message='Valid quantity and live premium required.');return;}setState(()=>busy=true);try{final r=await widget.api.postJson('/execution/intent',{'exchange_segment':'NSEFO','product':product,'price':'0','order_type':'MKT','quantity':q,'validity':'DAY','trading_symbol':'${x['trading_symbol']??''}','transaction_type':'B','trigger_price':'0','amo':'NO','disclosed_quantity':'0','reference_price':price,'live_price':price,'open_positions':0,'day_pnl':0.0});if(r['ok']!=true){throw Exception('Blocked: ${r['reasons']}');}if(!mounted)return;await showDialog(context:context,barrierDismissible:false,builder:(c)=>ConfirmTradeDialog(api:widget.api,intent:r,livePrice:price));}catch(e){if(mounted)setState(()=>message='$e');}finally{if(mounted)setState(()=>busy=false);}}
  @override Widget build(BuildContext context)=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      TextField(controller:underlying,decoration:const InputDecoration(labelText:'Underlying')),const SizedBox(height:10),
      TextField(controller:expiry,decoration:const InputDecoration(labelText:'Expiry',hintText:'Broker expiry format')),const SizedBox(height:10),
      Row(children:[Expanded(child:TextField(controller:ltp,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Underlying LTP'))),const SizedBox(width:10),Expanded(child:TextField(controller:step,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Strike step')))]),const SizedBox(height:10),
      Row(children:[Expanded(child:SegmentedButton<String>(segments:const [ButtonSegment(value:'CE',label:Text('CE')),ButtonSegment(value:'PE',label:Text('PE'))],selected:{type},onSelectionChanged:(v)=>setState(()=>type=v.first))),const SizedBox(width:10),Expanded(child:DropdownButtonFormField<String>(value:product,items:const [DropdownMenuItem(value:'MIS',child:Text('MIS')),DropdownMenuItem(value:'NRML',child:Text('NRML'))],onChanged:(v)=>setState(()=>product=v??product),decoration:const InputDecoration(labelText:'Product')))]),const SizedBox(height:12),
      FilledButton.icon(onPressed:busy?null:_scan,icon:const Icon(Icons.manage_search),label:Text(busy?'CHECKING LIVE QUOTES…':'FIND BEST OPTION')),
    ])),
    if(message!=null)Padding(padding:const EdgeInsets.only(top:10),child:Notice(message!)),
    if(selected!=null)...[const SizedBox(height:10),SelectedOptionCard(x:selected!),const SizedBox(height:10),TextField(controller:qty,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Quantity')),const SizedBox(height:14),SwipeGuard(label:'SWIPE TO PREPARE BUY',onTriggered:_prepare)],
    if(candidates.isNotEmpty)...[const SizedBox(height:20),const SectionTitle('OPTION QUALITY'),const SizedBox(height:8),OptionChainTable(rows:candidates.take(10).map(_map).toList(),selected:selected,onSelect:(x)=>setState(()=>selected=x))],
  ]);
}

class OrdersPanel extends StatefulWidget{const OrdersPanel({super.key,required this.api});final ApiService api;@override State<OrdersPanel>createState()=>_OrdersPanelState();}
class _OrdersPanelState extends State<OrdersPanel>{List<Map<String,dynamic>>rows=[];bool busy=false;String?message;@override void initState(){super.initState();_load();}
  Future<void>_load()async{setState(()=>busy=true);try{final raw=await widget.api.getAny('/orders');if(!mounted)return;setState((){rows=_collectOrderRows(raw).take(80).toList();message=rows.isEmpty?'No broker orders returned.':null;});}catch(e){if(mounted)setState(()=>message='$e');}finally{if(mounted)setState(()=>busy=false);}}
  Future<void>_cancel(Map<String,dynamic>x)async{final id=_orderId(x);if(id.isEmpty)return;try{await widget.api.postJson('/orders/cancel',{'order_id':id,'amo':'${x['amo']??'NO'}'});if(mounted)ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Cancel request sent to Kotak')));await _load();}catch(e){if(mounted)setState(()=>message='$e');}}
  @override Widget build(BuildContext context)=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    Row(children:[const Expanded(child:SectionTitle('BROKER ORDERS')),IconButton(onPressed:busy?null:_load,icon:const Icon(Icons.refresh))]),
    if(message!=null)Notice(message!),
    if(rows.isEmpty&&busy)const Padding(padding:EdgeInsets.all(30),child:Center(child:CircularProgressIndicator())),
    ...rows.map((x)=>Padding(padding:const EdgeInsets.only(bottom:8),child:OrderTile(api:widget.api,x:x,onRefresh:_load,onCancel:()=>_cancel(x)))),
  ]);
}

class OrderTile extends StatelessWidget{
  const OrderTile({super.key,required this.api,required this.x,required this.onRefresh,required this.onCancel});final ApiService api;final Map<String,dynamic>x;final VoidCallback onRefresh,onCancel;
  @override Widget build(BuildContext context){final status='${x['status']??x['order_status']??x['orderStatus']??'-'}'.toUpperCase();final canAct=!status.contains('COMPLETE')&&!status.contains('REJECT')&&!status.contains('CANCEL');return RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
    Row(children:[Expanded(child:Text('${x['trading_symbol']??x['tradingSymbol']??x['symbol']??'-'}',style:const TextStyle(fontWeight:FontWeight.w900,fontSize:16,color:KbColors.text))),RobotChip(icon:Icons.circle,label:status,active:status.contains('COMPLETE'))]),
    const SizedBox(height:6),Text('${x['transaction_type']??x['transactionType']??x['side']??'-'} • Qty ${x['quantity']??x['qty']??'-'} • Price ${x['price']??'-'}',style:const TextStyle(color:KbColors.textMuted)),
    const SizedBox(height:9),Row(children:[Expanded(child:Text('ID ${_orderId(x)}',style:const TextStyle(fontSize:11,color:KbColors.textFaint))),if(canAct)TextButton.icon(onPressed:()=>showDialog(context:context,builder:(c)=>ModifyOrderDialog(api:api,order:x,onDone:onRefresh)),icon:const Icon(Icons.edit,size:17),label:const Text('Modify')),if(canAct)TextButton.icon(onPressed:onCancel,icon:const Icon(Icons.close,size:17),label:const Text('Cancel'))]),
  ]));}
}

class ModifyOrderDialog extends StatefulWidget{const ModifyOrderDialog({super.key,required this.api,required this.order,required this.onDone});final ApiService api;final Map<String,dynamic>order;final VoidCallback onDone;@override State<ModifyOrderDialog>createState()=>_ModifyOrderDialogState();}
class _ModifyOrderDialogState extends State<ModifyOrderDialog>{late final TextEditingController price;late final TextEditingController qty;late final TextEditingController trigger;String type='L';bool busy=false;String?error;@override void initState(){super.initState();price=TextEditingController(text:'${widget.order['price']??'0'}');qty=TextEditingController(text:'${widget.order['quantity']??widget.order['qty']??'1'}');trigger=TextEditingController(text:'${widget.order['trigger_price']??widget.order['triggerPrice']??'0'}');type='${widget.order['order_type']??widget.order['orderType']??'L'}';}@override void dispose(){price.dispose();qty.dispose();trigger.dispose();super.dispose();}
  @override Widget build(BuildContext context)=>AlertDialog(title:const Text('Modify Kotak order'),content:Column(mainAxisSize:MainAxisSize.min,children:[DropdownButtonFormField<String>(value:['MKT','L','SL','SL-M'].contains(type)?type:'L',items:const [DropdownMenuItem(value:'MKT',child:Text('Market')),DropdownMenuItem(value:'L',child:Text('Limit')),DropdownMenuItem(value:'SL',child:Text('SL')),DropdownMenuItem(value:'SL-M',child:Text('SL-M'))],onChanged:(v)=>setState(()=>type=v??type),decoration:const InputDecoration(labelText:'Order type')),const SizedBox(height:8),TextField(controller:qty,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Quantity')),const SizedBox(height:8),TextField(controller:price,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Price')),const SizedBox(height:8),TextField(controller:trigger,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Trigger')),if(error!=null)Notice(error!)]),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Close')),FilledButton(onPressed:busy?null:()async{setState(()=>busy=true);try{await widget.api.postJson('/orders/modify',{'order_id':_orderId(widget.order),'price':price.text.trim(),'order_type':type,'quantity':qty.text.trim(),'validity':'${widget.order['validity']??'DAY'}','trigger_price':trigger.text.trim(),'disclosed_quantity':'0','amo':'${widget.order['amo']??'NO'}'});if(!mounted)return;Navigator.pop(context);widget.onDone();}catch(e){if(mounted)setState((){error='$e';busy=false;});}},child:Text(busy?'Sending…':'Modify'))]);}

class ConfirmTradeDialog extends StatefulWidget{const ConfirmTradeDialog({super.key,required this.api,required this.intent,required this.livePrice});final ApiService api;final Map<String,dynamic>intent;final double livePrice;@override State<ConfirmTradeDialog>createState()=>_ConfirmTradeDialogState();}
class _ConfirmTradeDialogState extends State<ConfirmTradeDialog>{bool busy=false;String? error;@override Widget build(BuildContext context){final s=_map(widget.intent['summary']);return AlertDialog(title:const Text('Confirm live order'),content:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[Text('${s['side']}  ${s['quantity']} × ${s['symbol']}',style:const TextStyle(fontWeight:FontWeight.w900,fontSize:17)),const SizedBox(height:8),Text('Live premium: \u20B9${widget.livePrice.toStringAsFixed(2)}'),Text('${s['order_type']??'MKT'} • ${s['product']??''}'),const SizedBox(height:12),const Text('This confirmation token is one-time and short-lived.',style:TextStyle(color:KbColors.textMuted)),if(error!=null)Padding(padding:const EdgeInsets.only(top:10),child:Text(error!,style:const TextStyle(color:Colors.red))) ]),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:busy?null:()async{setState(()=>busy=true);try{final r=await widget.api.postJson('/execution/${widget.intent['intent_id']}/confirm',{'confirmation_token':widget.intent['confirmation_token'],'live_price':widget.livePrice,'open_positions':0,'day_pnl':0.0});if(!mounted)return;Navigator.pop(context);ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(r['ok']==true?'Order submitted to Kotak':'Order blocked: ${r['reasons']}')));}catch(e){if(mounted)setState((){error='$e';busy=false;});}},child:Text(busy?'Submitting…':'CONFIRM ${('${s['side']??'ORDER'}').toUpperCase()}'))]);}}

class PortfolioPage extends StatefulWidget{const PortfolioPage({super.key,required this.api});final ApiService api;@override State<PortfolioPage>createState()=>_PortfolioPageState();}
class _PortfolioPageState extends State<PortfolioPage>{List<dynamic> p=[];Map<String,dynamic> sum={};String? error;bool busy=false;@override void initState(){super.initState();_load();}
 Future<void>_load()async{setState(()=>busy=true);try{final r=await widget.api.getJson('/portfolio/positions/live');if(mounted)setState((){p=(r['positions'] as List?)??[];sum=_map(r['summary']);error=null;});}catch(e){if(mounted)setState(()=>error='$e');}finally{if(mounted)setState(()=>busy=false);}}
 Future<void>_refreshBroker()async{try{await widget.api.postJson('/portfolio/positions/refresh',{});await _load();}catch(e){if(mounted)setState(()=>error='$e');}}
 Future<void>_exitAll()async{final c=TextEditingController();try{final ok=await showDialog<bool>(context:context,builder:(ctx)=>AlertDialog(title:const Text('EXIT ALL POSITIONS'),content:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[const Text('This can submit real market exit orders for every open position. Type EXIT ALL to continue.'),const SizedBox(height:12),TextField(controller:c,decoration:const InputDecoration(labelText:'Confirmation text'))]),actions:[TextButton(onPressed:()=>Navigator.pop(ctx,false),child:const Text('Cancel')),FilledButton(onPressed:()=>Navigator.pop(ctx,c.text.trim().toUpperCase()=='EXIT ALL'),child:const Text('Confirm Exit All'))]));if(ok!=true)return;final r=await widget.api.postJson('/portfolio/exit-all',{'confirmation_text':'EXIT ALL'});if(!mounted)return;ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(r['ok']==true?'Exit-all submitted':'Some exits failed')));await _load();}catch(e){if(mounted)setState(()=>error='$e');}finally{c.dispose();}}
 @override Widget build(BuildContext context)=>PageFrame(title:'Portfolio',actions:[IconButton(onPressed:busy?null:_refreshBroker,icon:const Icon(Icons.sync))],child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[RobotPanel(child:Row(children:[Expanded(child:_MiniMetric(label:'OPEN',value:'${sum['open_positions']??0}',icon:Icons.work_outline)),Expanded(child:_MiniMetric(label:'TRACKED',value:'${sum['tracked_positions']??0}',icon:Icons.track_changes)),Expanded(child:_MiniMetric(label:'MARKED',value:'${sum['marked_positions']??0}',icon:Icons.show_chart))])),const SizedBox(height:12),PnlHeader(value:_num(sum['day_mtm'])),if(_int(sum['open_positions'])>0)...[const SizedBox(height:10),OutlinedButton.icon(onPressed:busy?null:_exitAll,icon:const Icon(Icons.emergency_outlined),label:const Text('EXIT ALL POSITIONS'))],const SizedBox(height:14),if(error!=null)Notice(error!),if(p.isEmpty&&!busy)const EmptyState(icon:Icons.inbox_outlined,text:'No open positions'),...p.map((v)=>Padding(padding:const EdgeInsets.only(bottom:10),child:PositionTile(api:widget.api,x:_map(v),onDone:_load)))]));}

class PositionTile extends StatelessWidget {
  const PositionTile({super.key, required this.api, required this.x, required this.onDone});
  final ApiService api;
  final Map<String, dynamic> x;
  final VoidCallback onDone;

  @override
  Widget build(BuildContext context) {
    final q = _int(x['net_quantity'] ?? x['quantity']);
    final pnl = _num(x['mtm'] ?? x['pnl']);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${x['trading_symbol'] ?? x['symbol'] ?? '-'}', style: const TextStyle(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 3),
                      Text('Qty $q  •  Avg ${x['average_price'] ?? '-'}  •  LTP ${x['ltp'] ?? '-'}', style: const TextStyle(color: KbColors.textMuted)),
                    ],
                  ),
                ),
                Text(
                  _money(pnl),
                  style: TextStyle(fontWeight: FontWeight.w900, color: pnl >= 0 ? Colors.green.shade700 : Colors.red.shade700),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: q == 0 ? null : () => showDialog(context: context, builder: (c) => ExitPlanDialog(api: api, position: x)),
                  child: const Text('SL / Targets'),
                ),
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  onPressed: q == 0 ? null : () => showDialog(context:context,builder:(c)=>PositionExitDialog(api:api,position:x,onDone:onDone)),
                  icon: const Icon(Icons.logout),
                  label: const Text('Exit Position'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class PositionExitDialog extends StatefulWidget{
  const PositionExitDialog({super.key,required this.api,required this.position,required this.onDone});
  final ApiService api; final Map<String,dynamic> position; final VoidCallback onDone;
  @override State<PositionExitDialog> createState()=>_PositionExitDialogState();
}
class _PositionExitDialogState extends State<PositionExitDialog>{
  late final TextEditingController qty; bool busy=false; String? error;
  int get maxQty=>_int(widget.position['net_quantity']??widget.position['quantity']).abs();
  int get lot=>max(1,_int(widget.position['lot_size']??1));
  @override void initState(){super.initState();qty=TextEditingController(text:'$maxQty');}
  @override void dispose(){qty.dispose();super.dispose();}
  void _preset(double fraction){var q=(maxQty*fraction).floor();if(lot>1){q=(q~/lot)*lot;}if(q<=0)q=min(maxQty,lot);qty.text='${min(q,maxQty)}';setState((){});}
  Future<void>_prepare()async{final q=int.tryParse(qty.text.trim())??0;if(q<=0||q>maxQty){setState(()=>error='Quantity must be between 1 and $maxQty');return;}setState((){busy=true;error=null;});try{final r=await widget.api.postJson('/portfolio/exit-intent',{'position_key':'${widget.position['key']}','quantity':q});if(!mounted)return;if(r['ok']!=true){setState(()=>error='Exit blocked: ${r['reasons']}');return;}await showDialog(context:context,builder:(c)=>ConfirmTradeDialog(api:widget.api,intent:r,livePrice:_num(widget.position['ltp']??widget.position['average_price'])));if(!mounted)return;Navigator.pop(context);widget.onDone();}catch(e){if(mounted)setState(()=>error='$e');}finally{if(mounted)setState(()=>busy=false);}}
  @override Widget build(BuildContext context)=>AlertDialog(title:Text('Exit ${widget.position['trading_symbol']??'Position'}'),content:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text('Open qty: $maxQty  •  Lot: $lot',style:const TextStyle(color:KbColors.textMuted)),const SizedBox(height:10),Wrap(spacing:8,children:[ActionChip(label:const Text('25%'),onPressed:()=>_preset(.25)),ActionChip(label:const Text('50%'),onPressed:()=>_preset(.50)),ActionChip(label:const Text('100%'),onPressed:()=>_preset(1.0))]),const SizedBox(height:10),TextField(controller:qty,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Exit quantity')),if(error!=null)Padding(padding:const EdgeInsets.only(top:8),child:Text(error!,style:const TextStyle(color:Colors.redAccent)))]),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton.icon(onPressed:busy?null:_prepare,icon:const Icon(Icons.verified_user_outlined),label:Text(busy?'Checking…':'Prepare Exit'))]);
}

class MorePage extends StatefulWidget{const MorePage({super.key,required this.api,required this.initialUrl,required this.onUrl,required this.ws});final ApiService api;final String initialUrl;final ValueChanged<String> onUrl;final bool ws;@override State<MorePage>createState()=>_MorePageState();}
class _MorePageState extends State<MorePage>{late final TextEditingController c=TextEditingController(text:widget.initialUrl);Map<String,dynamic> risk={};Map<String,dynamic> execution={};dynamic orders,holdings,limits,journal;String? msg;bool busy=false;@override void initState(){super.initState();_load();}@override void dispose(){c.dispose();super.dispose();}
 Future<void>_load()async{try{final b=await widget.api.getJson('/app/bootstrap');if(mounted)setState((){risk=_map(b['risk']);execution=_map(b['execution']);});}catch(e){if(mounted)setState(()=>msg='$e');}}
 Future<void>_toggleRisk(bool on)async{try{final r=await widget.api.postJson('/risk/trading',{'enabled':on});setState(()=>risk=r);}catch(e){setState(()=>msg='$e');}}
 Future<void>_toggleArm(bool on)async{try{final r=await widget.api.postJson('/execution/arm',{'enabled':on});setState(()=>execution=r);}catch(e){setState(()=>msg='$e');}}
 Future<void>_login()async{await showDialog(context:context,builder:(c)=>LoginDialog(api:widget.api));await _load();}
 Future<void>_logout()async{try{await widget.api.postJson('/auth/logout',{});await _load();}catch(e){setState(()=>msg='$e');}}
 Future<void>_syncCore()async{try{final r=await widget.api.postJson('/instruments/sync-core',{});setState(()=>msg='Core indices synced: ${r['ok']==true?'OK':'CHECK'}');}catch(e){setState(()=>msg='$e');}}
 Future<void>_recover()async{try{final r=await widget.api.postJson('/system/recover',{});setState(()=>msg=r['ok']==true?'Recovery complete':'Recovery completed with warnings');await _load();}catch(e){setState(()=>msg='$e');}}
 Future<void>_account()async{setState(()=>busy=true);try{final values=await Future.wait([widget.api.getAny('/orders'),widget.api.getAny('/portfolio/holdings'),widget.api.getAny('/portfolio/limits'),widget.api.getAny('/journal?limit=30')]);if(mounted)setState((){orders=values[0];holdings=values[1];limits=values[2];journal=values[3];msg=null;});}catch(e){if(mounted)setState(()=>msg='$e');}finally{if(mounted)setState(()=>busy=false);}}
 Future<void>_killSwitch()async{final ok=await showDialog<bool>(context:context,builder:(ctx)=>AlertDialog(title:const Text('Activate Kill Switch?'),content:const Text('This immediately blocks/halts live execution. Use only when you intend to stop trading.'),actions:[TextButton(onPressed:()=>Navigator.pop(ctx,false),child:const Text('Cancel')),FilledButton(style:FilledButton.styleFrom(backgroundColor:KbColors.coral),onPressed:()=>Navigator.pop(ctx,true),child:const Text('ACTIVATE'))]));if(ok!=true)return;try{await widget.api.postJson('/execution/kill-switch',{});await _load();if(mounted)ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Kill switch activated')));}catch(e){if(mounted)setState(()=>msg='$e');}}
 @override Widget build(BuildContext context){final orderCount=_collectOrderRows(orders).length;final holdingCount=_recordCount(holdings);final fundRows=_fundMetrics(limits);final journalCount=_recordCount(journal);return PageFrame(title:'More',child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
   const SectionTitle('KOTAK SESSION'),const SizedBox(height:8),Row(children:[Expanded(child:FilledButton.icon(onPressed:_login,icon:const Icon(Icons.login),label:const Text('Login TOTP'))),const SizedBox(width:8),Expanded(child:OutlinedButton.icon(onPressed:_logout,icon:const Icon(Icons.logout),label:const Text('Logout')))]),const SizedBox(height:8),OutlinedButton.icon(onPressed:_syncCore,icon:const Icon(Icons.sync_alt),label:const Text('Sync market indices')),const SizedBox(height:8),OutlinedButton.icon(onPressed:_recover,icon:const Icon(Icons.restore),label:const Text('Recover session data')),
   const SizedBox(height:18),const SectionTitle('SAFETY'),const SizedBox(height:8),SwitchListTile(tileColor:KbColors.card,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(14)),title:const Text('Risk trading gate'),subtitle:const Text('Required before execution can arm'),value:risk['trading_enabled']==true,onChanged:_toggleRisk),const SizedBox(height:8),SwitchListTile(tileColor:KbColors.card,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(14)),title:const Text('Execution arm'),subtitle:const Text('Second live-order safety gate'),value:execution['armed']==true,onChanged:_toggleArm),const SizedBox(height:8),FilledButton.icon(style:FilledButton.styleFrom(backgroundColor:KbColors.coral,foregroundColor:Colors.white),onPressed:_killSwitch,icon:const Icon(Icons.emergency),label:const Text('EMERGENCY KILL SWITCH')),
   const SizedBox(height:18),const SectionTitle('ACCOUNT SNAPSHOT'),const SizedBox(height:8),OutlinedButton.icon(onPressed:busy?null:_account,icon:const Icon(Icons.sync),label:Text(busy?'Loading account…':'Refresh account data')),
   if(orders!=null||holdings!=null||limits!=null)...[const SizedBox(height:10),RobotPanel(glow:false,child:Column(children:[Row(children:[Expanded(child:_MiniMetric(label:'ORDERS',value:'$orderCount',icon:Icons.receipt_long)),Expanded(child:_MiniMetric(label:'HOLDINGS',value:'$holdingCount',icon:Icons.account_balance_wallet_outlined)),Expanded(child:_MiniMetric(label:'JOURNAL',value:'$journalCount',icon:Icons.history))]),if(fundRows.isNotEmpty)...[const Divider(height:22),...fundRows.take(6).map((e)=>Padding(padding:const EdgeInsets.symmetric(vertical:4),child:Row(children:[Expanded(child:Text(e.$1,style:const TextStyle(fontSize:11,color:KbColors.textMuted))),Text(e.$2,style:const TextStyle(fontSize:12,fontWeight:FontWeight.w900,color:KbColors.text))])))] ]))],
   const SizedBox(height:18),ExpansionTile(tilePadding:EdgeInsets.zero,title:const Text('Advanced connection',style:TextStyle(fontWeight:FontWeight.w800)),subtitle:Text(widget.ws?'Backend connected':'Backend offline',style:TextStyle(color:widget.ws?KbColors.cyan:KbColors.coral)),children:[TextField(controller:c,decoration:InputDecoration(labelText:'Backend URL',suffixIcon:Icon(widget.ws?Icons.cloud_done:Icons.cloud_off))),const SizedBox(height:10),FilledButton(onPressed:()async{final v=c.text.trim().replaceAll(RegExp(r'/$'),'');widget.onUrl(v);setState(()=>msg='Connection saved');},child:const Text('Save connection'))]),
   if(msg!=null)Padding(padding:const EdgeInsets.only(top:10),child:Notice(msg!)),
 ]));}
}
class RobotPanel extends StatelessWidget{
  const RobotPanel({super.key,required this.child,this.padding=const EdgeInsets.all(16),this.glow=true,this.onTap,this.highlight=false});
  final Widget child; final EdgeInsets padding; final bool glow,highlight; final VoidCallback? onTap;
  @override Widget build(BuildContext context){
    final panel=Container(
      decoration:BoxDecoration(
        gradient:LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:highlight?const [Color(0xff123a48),Color(0xff082631)]:const [Color(0xff0c2230),Color(0xff071620)]),
        borderRadius:BorderRadius.circular(18),
        border:Border.all(color:highlight?KbColors.cyan:const Color(0xff1d8eaa),width:highlight?1.5:1),
        boxShadow:(glow||highlight)?const [BoxShadow(color:Color(0x4400cfff),blurRadius:16,spreadRadius:1),BoxShadow(color:Color(0x220078e6),blurRadius:30,offset:Offset(0,8))]:const [],
      ),
      child:ClipRRect(
        borderRadius:BorderRadius.circular(18),
        child:Stack(children:[
          Positioned(right:-36,top:-48,child:Container(width:120,height:120,decoration:const BoxDecoration(shape:BoxShape.circle,gradient:RadialGradient(colors:[Color(0x4400e5ff),Color(0x0000d8ff)])))),
          Padding(padding:padding,child:child),
        ]),
      ),
    );
    return onTap==null?panel:InkWell(onTap:onTap,borderRadius:BorderRadius.circular(18),child:panel);
  }
}

class RobotScanLine extends StatefulWidget{const RobotScanLine({super.key});@override State<RobotScanLine>createState()=>_RobotScanLineState();}
class _RobotScanLineState extends State<RobotScanLine>with SingleTickerProviderStateMixin{
  late final AnimationController c=AnimationController(vsync:this,duration:const Duration(milliseconds:2600))..repeat();
  @override void dispose(){c.dispose();super.dispose();}
  @override Widget build(BuildContext context)=>IgnorePointer(child:LayoutBuilder(builder:(context,b)=>AnimatedBuilder(animation:c,builder:(context,_){return Positioned(top:(b.maxHeight-2)*c.value,left:0,right:0,child:Container(height:2,decoration:const BoxDecoration(gradient:LinearGradient(colors:[Color(0x0000bfe8),Color(0x7700bfe8),Color(0x0000bfe8)]))));})));
}

class BalanceCard extends StatelessWidget{
  const BalanceCard({super.key,required this.mtm,required this.open,required this.armed,required this.trading});
  final double mtm;final int open;final bool armed,trading;
  @override Widget build(BuildContext context)=>RobotPanel(padding:EdgeInsets.zero,child:Stack(children:[
    const RobotScanLine(),
    Padding(padding:const EdgeInsets.all(18),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
      Row(children:[
        const Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('ACCOUNT CORE',style:TextStyle(fontSize:10,fontWeight:FontWeight.w900,letterSpacing:1.6,color:KbColors.cyan)),SizedBox(height:3),Text('TODAY MTM',style:TextStyle(fontSize:12,fontWeight:FontWeight.w800,color:KbColors.textMuted))])),
        const RobotChip(icon:Icons.memory,label:'NEO CORE',active:true),
      ]),
      const SizedBox(height:8),
      Text(_money(mtm,sign:true),style:Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight:FontWeight.w900,color:mtm>=0?KbColors.emerald:KbColors.coral)),
      const SizedBox(height:14),
      Wrap(spacing:8,runSpacing:8,children:[RobotChip(icon:Icons.work_outline,label:'$open OPEN',active:open>0),RobotChip(icon:Icons.shield_outlined,label:trading?'RISK ON':'RISK OFF',active:trading),RobotChip(icon:armed?Icons.lock_open:Icons.lock_outline,label:armed?'ARMED':'DISARMED',active:armed)]),
    ])),
  ]));
}

class RobotChip extends StatelessWidget{
  const RobotChip({super.key,required this.icon,required this.label,required this.active});final IconData icon;final String label;final bool active;
  @override Widget build(BuildContext context)=>Container(padding:const EdgeInsets.symmetric(horizontal:10,vertical:7),decoration:BoxDecoration(
    color:active?KbColors.emerald.withValues(alpha:.09):KbColors.cardSoft,
    borderRadius:BorderRadius.circular(12),border:Border.all(color:active?KbColors.emerald.withValues(alpha:.65):KbColors.border),
    boxShadow:active?[BoxShadow(color:KbColors.emerald.withValues(alpha:.12),blurRadius:10)]:const [],
  ),child:Row(mainAxisSize:MainAxisSize.min,children:[Icon(icon,size:15,color:active?KbColors.emerald:KbColors.textMuted),const SizedBox(width:6),Text(label,style:TextStyle(fontSize:11,fontWeight:FontWeight.w900,color:active?KbColors.emerald:KbColors.textSecondary))]));
}

class PnlHeader extends StatelessWidget{const PnlHeader({super.key,required this.value});final double value;@override Widget build(BuildContext context)=>RobotPanel(child:Row(children:[Container(width:44,height:44,decoration:BoxDecoration(shape:BoxShape.circle,color:KbColors.cardSoft,border:Border.all(color:KbColors.borderStrong),boxShadow:const [BoxShadow(color:Color(0x3300e5ff),blurRadius:14)]),child:const Icon(Icons.insights,color:KbColors.cyan)),const SizedBox(width:12),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[const Text('LIVE MTM',style:TextStyle(fontSize:11,fontWeight:FontWeight.w900,letterSpacing:1.2,color:KbColors.textMuted)),Text(_money(value),style:Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight:FontWeight.w900,color:value>=0?KbColors.emerald:KbColors.coral))]))]));}

class StatusPill extends StatelessWidget{const StatusPill({super.key,required this.ok,required this.label});final bool ok;final String label;@override Widget build(BuildContext context)=>Container(margin:const EdgeInsets.symmetric(vertical:8),padding:const EdgeInsets.symmetric(horizontal:10,vertical:7),decoration:BoxDecoration(color:(ok?KbColors.emerald:KbColors.amber).withValues(alpha:.08),borderRadius:BorderRadius.circular(20),border:Border.all(color:(ok?KbColors.emerald:KbColors.amber).withValues(alpha:.65)),boxShadow:[BoxShadow(color:(ok?KbColors.emerald:KbColors.amber).withValues(alpha:.14),blurRadius:12)]),child:Row(mainAxisSize:MainAxisSize.min,children:[Icon(Icons.circle,size:8,color:ok?KbColors.emerald:KbColors.amber),const SizedBox(width:6),Text(label,style:TextStyle(fontSize:10,fontWeight:FontWeight.w900,letterSpacing:.7,color:ok?KbColors.emerald:KbColors.amber))]));}

class SectionTitle extends StatelessWidget{const SectionTitle(this.t,{super.key});final String t;@override Widget build(BuildContext context)=>Row(children:[Container(width:3,height:18,decoration:BoxDecoration(color:KbColors.cyan,borderRadius:BorderRadius.circular(3),boxShadow:const [BoxShadow(color:Color(0x6600e5ff),blurRadius:10)])),const SizedBox(width:8),Text(t,style:Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight:FontWeight.w900,letterSpacing:.8,color:KbColors.text))]);}

class InfoTile extends StatelessWidget{const InfoTile({super.key,required this.icon,required this.title,required this.value,required this.good});final IconData icon;final String title,value;final bool good;@override Widget build(BuildContext context)=>RobotPanel(glow:false,padding:const EdgeInsets.symmetric(horizontal:14,vertical:7),child:ListTile(contentPadding:EdgeInsets.zero,leading:Container(width:42,height:42,decoration:BoxDecoration(shape:BoxShape.circle,color:KbColors.cardSoft,border:Border.all(color:KbColors.border)),child:Icon(icon,color:KbColors.cyan)),title:Text(title,style:const TextStyle(fontWeight:FontWeight.w800,color:KbColors.text)),trailing:Row(mainAxisSize:MainAxisSize.min,children:[Icon(Icons.circle,size:8,color:good?KbColors.emerald:KbColors.amber),const SizedBox(width:6),Text(value,style:TextStyle(fontSize:11,fontWeight:FontWeight.w900,color:good?KbColors.emerald:KbColors.amber))])));}

class Notice extends StatelessWidget{const Notice(this.t,{super.key});final String t;@override Widget build(BuildContext context)=>Padding(padding:const EdgeInsets.symmetric(vertical:8),child:Container(decoration:BoxDecoration(color:KbColors.amber.withValues(alpha:.07),borderRadius:BorderRadius.circular(14),border:Border.all(color:KbColors.amber.withValues(alpha:.42))),padding:const EdgeInsets.all(12),child:Text(t,style:const TextStyle(color:KbColors.textSecondary,fontWeight:FontWeight.w600))));}

class EmptyState extends StatelessWidget{const EmptyState({super.key,required this.icon,required this.text});final IconData icon;final String text;@override Widget build(BuildContext context)=>RobotPanel(glow:false,child:Padding(padding:const EdgeInsets.symmetric(vertical:24),child:Column(children:[Container(width:58,height:58,decoration:BoxDecoration(shape:BoxShape.circle,color:KbColors.cardSoft,border:Border.all(color:KbColors.borderStrong),boxShadow:const [BoxShadow(color:Color(0x3300e5ff),blurRadius:18)]),child:Icon(icon,size:28,color:KbColors.cyan)),const SizedBox(height:12),Text(text,textAlign:TextAlign.center,style:const TextStyle(color:KbColors.textMuted,fontWeight:FontWeight.w700))])));}

class _MiniMetric extends StatelessWidget{const _MiniMetric({required this.label,required this.value,required this.icon});final String label,value;final IconData icon;@override Widget build(BuildContext context)=>Padding(padding:const EdgeInsets.symmetric(horizontal:4),child:Column(children:[Icon(icon,size:17,color:KbColors.cyan),const SizedBox(height:5),Text(value,maxLines:1,style:const TextStyle(fontSize:15,fontWeight:FontWeight.w900,color:KbColors.text)),const SizedBox(height:2),Text(label,maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(fontSize:8,letterSpacing:.5,fontWeight:FontWeight.w800,color:KbColors.textMuted))]));}

class SignalCard extends StatelessWidget{const SignalCard(this.x,{super.key,required this.onTap});final Map<String,dynamic>x;final VoidCallback onTap;@override Widget build(BuildContext context){final side='${x['side']??''}'.toUpperCase();final buy=side=='BUY';return RobotPanel(onTap:onTap,child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[Container(width:40,height:40,decoration:BoxDecoration(shape:BoxShape.circle,color:(buy?KbColors.emerald:KbColors.coral).withValues(alpha:.10),border:Border.all(color:(buy?KbColors.emerald:KbColors.coral).withValues(alpha:.55)),boxShadow:[BoxShadow(color:(buy?KbColors.emerald:KbColors.coral).withValues(alpha:.14),blurRadius:12)]),child:Icon(buy?Icons.trending_up:Icons.trending_down,color:buy?KbColors.emerald:KbColors.coral)),const SizedBox(width:10),Expanded(child:Text('${x['symbol_key']??x['symbol']??'Signal'}',style:const TextStyle(fontWeight:FontWeight.w900,fontSize:16,color:KbColors.text))),Container(padding:const EdgeInsets.symmetric(horizontal:9,vertical:5),decoration:BoxDecoration(color:(buy?KbColors.emerald:KbColors.coral).withValues(alpha:.10),borderRadius:BorderRadius.circular(12),border:Border.all(color:(buy?KbColors.emerald:KbColors.coral).withValues(alpha:.4))),child:Text(side,style:TextStyle(fontWeight:FontWeight.w900,color:buy?KbColors.emerald:KbColors.coral)))]),const SizedBox(height:12),Text('ENTRY ${x['entry']??'-'}   SL ${x['stop']??x['stop_loss']??'-'}   T1 ${x['target1']??'-'}   T2 ${x['target2']??'-'}',style:const TextStyle(fontSize:12,fontWeight:FontWeight.w800,color:KbColors.textSecondary)),const SizedBox(height:8),Row(children:[const Icon(Icons.bolt,size:15,color:KbColors.cyan),const SizedBox(width:4),Text('${x['state']??'ACTIVE'}',style:const TextStyle(fontSize:11,fontWeight:FontWeight.w900,color:KbColors.cyan)),const SizedBox(width:10),Text('SCORE ${x['score']??'-'} • RR ${x['rr']??'-'}',style:const TextStyle(fontSize:10,fontWeight:FontWeight.w800,color:KbColors.textMuted)),const Spacer(),const Icon(Icons.chevron_right,color:KbColors.textMuted)])]));}}

class MetricGrid extends StatelessWidget{const MetricGrid({super.key,required this.items});final List<(String,dynamic)>items;@override Widget build(BuildContext context)=>Wrap(spacing:8,runSpacing:8,children:items.map((e)=>Container(width:(MediaQuery.sizeOf(context).width-56)/2,padding:const EdgeInsets.all(12),decoration:BoxDecoration(color:KbColors.cardSoft,borderRadius:BorderRadius.circular(12),border:Border.all(color:KbColors.border)),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(e.$1,style:const TextStyle(color:KbColors.textMuted,fontSize:11)),const SizedBox(height:3),Text('${e.$2??'-'}',style:const TextStyle(fontWeight:FontWeight.w900,color:KbColors.text))]))).toList());}

class SelectedOptionCard extends StatelessWidget{const SelectedOptionCard({super.key,required this.x});final Map<String,dynamic>x;@override Widget build(BuildContext context)=>RobotPanel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[Expanded(child:Text('${x['trading_symbol']??'-'}',style:const TextStyle(fontWeight:FontWeight.w900,fontSize:17,color:KbColors.text))),RobotChip(icon:Icons.auto_graph,label:'SCORE ${x['score']??'-'}',active:true)]),const SizedBox(height:5),Text('\u20B9${_num(x['ltp']).toStringAsFixed(2)} • Strike ${x['strike']??'-'} • Spread ${x['spread_pct']??'n/a'}%',style:const TextStyle(color:KbColors.textMuted)),if((x['reasons'] as List?)?.isNotEmpty==true)Padding(padding:const EdgeInsets.only(top:6),child:Text('${x['reasons']}',style:const TextStyle(fontSize:11,color:KbColors.textMuted))) ]));}

class CandidateTile extends StatelessWidget{const CandidateTile({super.key,required this.x,required this.selected,required this.onTap});final Map<String,dynamic>x;final bool selected;final VoidCallback onTap;@override Widget build(BuildContext context)=>RobotPanel(onTap:onTap,highlight:selected,glow:selected,child:Row(children:[Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('${x['trading_symbol']??'-'}',style:const TextStyle(fontWeight:FontWeight.w800,color:KbColors.text)),const SizedBox(height:3),Text('LTP ${x['ltp']??'-'} • Spread ${x['spread_pct']??'n/a'}%',style:const TextStyle(color:KbColors.textMuted))])),Text('${x['score']??'-'}',style:const TextStyle(fontWeight:FontWeight.w900,color:KbColors.cyan))]));}

class OptionChainTable extends StatelessWidget{const OptionChainTable({super.key,required this.rows,required this.selected,required this.onSelect});final List<Map<String,dynamic>>rows;final Map<String,dynamic>?selected;final ValueChanged<Map<String,dynamic>>onSelect;@override Widget build(BuildContext context)=>RobotPanel(glow:false,child:Column(children:[const Row(children:[Expanded(flex:3,child:Text('CONTRACT',style:TextStyle(fontWeight:FontWeight.w800,color:KbColors.textMuted))),Expanded(child:Text('LTP',textAlign:TextAlign.right,style:TextStyle(fontWeight:FontWeight.w800,color:KbColors.textMuted))),Expanded(child:Text('SPREAD',textAlign:TextAlign.right,style:TextStyle(fontWeight:FontWeight.w800,color:KbColors.textMuted))),Expanded(child:Text('SCORE',textAlign:TextAlign.right,style:TextStyle(fontWeight:FontWeight.w800,color:KbColors.textMuted)))]),const Divider(),...rows.map((x){final isSel=selected!=null&&('${x['instrument_token']??x['token']}'=='${selected!['instrument_token']??selected!['token']}');return InkWell(onTap:()=>onSelect(x),borderRadius:BorderRadius.circular(10),child:Container(padding:const EdgeInsets.symmetric(vertical:10,horizontal:4),decoration:BoxDecoration(color:isSel?KbColors.cyan.withValues(alpha:.08):null,borderRadius:BorderRadius.circular(10),border:isSel?Border.all(color:KbColors.cyan.withValues(alpha:.35)):null),child:Row(children:[Expanded(flex:3,child:Text('${x['trading_symbol']??'-'}',maxLines:1,overflow:TextOverflow.ellipsis,style:TextStyle(color:KbColors.text,fontWeight:isSel?FontWeight.w900:FontWeight.w600))),Expanded(child:Text(_num(x['ltp']).toStringAsFixed(2),textAlign:TextAlign.right,style:const TextStyle(color:KbColors.textSecondary))),Expanded(child:Text('${x['spread_pct']??'n/a'}',textAlign:TextAlign.right,style:const TextStyle(color:KbColors.textSecondary))),Expanded(child:Text('${x['score']??'-'}',textAlign:TextAlign.right,style:const TextStyle(color:KbColors.cyan,fontWeight:FontWeight.w900)))])));})]));}

class SwipeGuard extends StatefulWidget{const SwipeGuard({super.key,required this.label,required this.onTriggered});final String label;final Future<void> Function() onTriggered;@override State<SwipeGuard>createState()=>_SwipeGuardState();}
class _SwipeGuardState extends State<SwipeGuard>{double v=0;bool busy=false;@override Widget build(BuildContext context)=>Column(children:[Container(padding:const EdgeInsets.symmetric(horizontal:10),decoration:BoxDecoration(color:KbColors.cardSoft,borderRadius:BorderRadius.circular(18),border:Border.all(color:KbColors.borderStrong),boxShadow:const [BoxShadow(color:Color(0x2200e5ff),blurRadius:14)]),child:Row(children:[const Icon(Icons.swipe_right,color:KbColors.cyan),Expanded(child:Slider(value:v,onChanged:busy?null:(n)=>setState(()=>v=n),onChangeEnd:(n)async{if(n>.92){setState(()=>busy=true);await widget.onTriggered();if(mounted)setState(()=>busy=false);}if(mounted)setState(()=>v=0);}),),Text(busy?'CHECKING…':widget.label,style:const TextStyle(fontSize:11,fontWeight:FontWeight.w900,color:KbColors.text))])),const SizedBox(height:4),const Text('Full swipe prepares the one-time server confirmation.',style:TextStyle(fontSize:10,color:KbColors.textMuted))]);}

class TickCard extends StatelessWidget{const TickCard({super.key,required this.row,this.isHot=false});final Map<String,dynamic>row;final bool isHot;@override Widget build(BuildContext context){final p=_num(row['ltp']??row['last_traded_price']??row['lp']??row['price']);return RobotPanel(glow:isHot,padding:const EdgeInsets.symmetric(horizontal:14,vertical:8),child:ListTile(contentPadding:EdgeInsets.zero,leading:Container(width:42,height:42,decoration:BoxDecoration(shape:BoxShape.circle,color:KbColors.cardSoft,border:Border.all(color:KbColors.borderStrong)),child:Icon(isHot?Icons.bolt:Icons.show_chart,color:KbColors.cyan)),title:Text('${row['trading_symbol']??row['symbol']??row['instrument_token']??row['token']??'Live tick'}',style:const TextStyle(fontWeight:FontWeight.w900,color:KbColors.text)),subtitle:Text('Broker stream${row['exchange_segment']!=null?' • ${row['exchange_segment']}':''}',style:const TextStyle(color:KbColors.textMuted)),trailing:Text(p>0?'\u20B9${p.toStringAsFixed(2)}':'LIVE',style:const TextStyle(fontWeight:FontWeight.w900,fontSize:17,color:KbColors.cyan))));}}

class JsonPanel extends StatelessWidget{const JsonPanel({super.key,required this.title,required this.data});final String title;final dynamic data;@override Widget build(BuildContext context){String text;try{text=const JsonEncoder.withIndent('  ').convert(data);}catch(_){text='$data';}if(text.length>3000)text='${text.substring(0,3000)}\n…';return Padding(padding:const EdgeInsets.only(top:10),child:ExpansionTile(tilePadding:const EdgeInsets.symmetric(horizontal:12),collapsedBackgroundColor:KbColors.card,backgroundColor:KbColors.card,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(14)),collapsedShape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(14)),title:Text(title,style:const TextStyle(fontWeight:FontWeight.w800)),children:[Padding(padding:const EdgeInsets.all(12),child:SelectableText(text,style:const TextStyle(fontFamily:'monospace',fontSize:11))) ]));}}


class LoginDialog extends StatefulWidget{const LoginDialog({super.key,required this.api});final ApiService api;@override State<LoginDialog>createState()=>_LoginDialogState();}
class _LoginDialogState extends State<LoginDialog>{final c=TextEditingController();bool busy=false;String? err;@override void dispose(){c.dispose();super.dispose();}@override Widget build(BuildContext context)=>AlertDialog(title:const Text('Connect Kotak Neo'),content:Column(mainAxisSize:MainAxisSize.min,children:[const Text('Enter the current Kotak TOTP. MPIN and account identifiers stay on the backend environment, not in the app.',style:TextStyle(color:KbColors.textMuted)),const SizedBox(height:12),TextField(controller:c,keyboardType:TextInputType.number,maxLength:8,decoration:const InputDecoration(labelText:'TOTP')),if(err!=null)Text(err!,style:const TextStyle(color:Colors.red))]),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:busy?null:()async{if(c.text.trim().length<6)return;setState(()=>busy=true);try{await widget.api.postJson('/auth/login',{'totp':c.text.trim()});if(!mounted)return;Navigator.pop(context);ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Kotak connected')));}catch(e){if(mounted)setState((){err='$e';busy=false;});}},child:Text(busy?'Connecting…':'Connect'))]);}

class ExitPlanDialog extends StatefulWidget{const ExitPlanDialog({super.key,required this.api,required this.position});final ApiService api;final Map<String,dynamic>position;@override State<ExitPlanDialog>createState()=>_ExitPlanDialogState();}
class _ExitPlanDialogState extends State<ExitPlanDialog>{final sl=TextEditingController(),t1=TextEditingController(),t2=TextEditingController();bool auto=false,busy=false;String? msg;@override void dispose(){sl.dispose();t1.dispose();t2.dispose();super.dispose();}@override Widget build(BuildContext context)=>AlertDialog(title:Text('${widget.position['trading_symbol']??'Position'} levels'),content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[TextField(controller:sl,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Stop loss')),const SizedBox(height:8),TextField(controller:t1,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Target 1')),const SizedBox(height:8),TextField(controller:t2,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:const InputDecoration(labelText:'Target 2')),SwitchListTile(contentPadding:EdgeInsets.zero,title:const Text('Auto-exit'),subtitle:const Text('OFF by default'),value:auto,onChanged:(v)=>setState(()=>auto=v)),if(msg!=null)Notice(msg!)])),actions:[TextButton(onPressed:busy?null:()=>Navigator.pop(context),child:const Text('Cancel')),FilledButton(onPressed:busy?null:()async{setState(()=>busy=true);try{final body=<String,dynamic>{'position_key':'${widget.position['key']}','auto_exit':auto,'target1_fraction':0.5};if(_double(sl.text)>0)body['stop_loss']=_double(sl.text);if(_double(t1.text)>0)body['target1']=_double(t1.text);if(_double(t2.text)>0)body['target2']=_double(t2.text);await widget.api.postJson('/portfolio/exit-plan',body);if(!mounted)return;Navigator.pop(context);ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Exit plan saved')));}catch(e){if(mounted)setState((){msg='$e';busy=false;});}},child:const Text('Save'))]);}

class IndexStrip extends StatelessWidget{
  const IndexStrip({super.key,required this.items});
  final List<dynamic>items;
  Map<String,dynamic>? _pick(String key){
    for(final v in items){final x=_map(v);final label='${x['label']??''}'.toUpperCase().replaceAll(' ','');if(label.contains(key))return x;}
    return null;
  }
  Widget _tile(String label,Map<String,dynamic>? x){
    final tick=_map(x?['tick']);
    final p=_num(tick['last_traded_price']??tick['ltp']??tick['price']);
    final change=_num(tick['net_change_percent']??tick['change_percent']??tick['percent_change']);
    final live=p>0; final up=change>=0;
    return Expanded(child:Container(
      height:92,padding:const EdgeInsets.fromLTRB(10,10,10,9),
      decoration:BoxDecoration(
        gradient:const LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[Color(0xF20A2443),Color(0xF2041025)]),
        borderRadius:BorderRadius.circular(14),border:Border.all(color:live?KbColors.borderStrong:KbColors.border),
        boxShadow:live?const [BoxShadow(color:Color(0x2200DFFF),blurRadius:12)]:const [],
      ),
      child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
        Row(children:[Expanded(child:Text(label,maxLines:1,style:const TextStyle(fontSize:9,fontWeight:FontWeight.w900,letterSpacing:.5,color:KbColors.textSecondary))),Container(width:5,height:5,decoration:BoxDecoration(shape:BoxShape.circle,color:live?KbColors.cyan:KbColors.textFaint))]),
        const Spacer(),
        Text(live?p.toStringAsFixed(2):'--',maxLines:1,style:const TextStyle(fontSize:16,fontWeight:FontWeight.w900,color:KbColors.text)),
        const SizedBox(height:3),
        Text(live&&change!=0?'${up?'+':''}${change.toStringAsFixed(2)}%':'LIVE',style:TextStyle(fontSize:8,fontWeight:FontWeight.w900,color:live?(up?KbColors.emerald:KbColors.coral):KbColors.textMuted)),
      ]),
    ));
  }
  @override Widget build(BuildContext context)=>Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
    Row(children:[const Expanded(child:Text('MARKET PULSE',style:TextStyle(fontSize:10,letterSpacing:1.4,fontWeight:FontWeight.w900,color:KbColors.cyan))),Container(width:6,height:6,decoration:const BoxDecoration(shape:BoxShape.circle,color:KbColors.emerald,boxShadow:[BoxShadow(color:Color(0x8835F08A),blurRadius:8)])),const SizedBox(width:5),const Text('NEO LIVE',style:TextStyle(fontSize:8,fontWeight:FontWeight.w900,color:KbColors.textMuted))]),
    const SizedBox(height:7),
    Row(children:[_tile('NIFTY',_pick('NIFTY50')??_pick('NIFTY')),const SizedBox(width:6),_tile('BANKNIFTY',_pick('NIFTYBANK')??_pick('BANK')),const SizedBox(width:6),_tile('SENSEX',_pick('SENSEX'))]),
  ]);
}

class _HudDivider extends StatelessWidget{const _HudDivider();@override Widget build(BuildContext context)=>Container(width:1,height:38,color:KbColors.border);}
class _HomeMetric extends StatelessWidget{const _HomeMetric({required this.label,required this.value,required this.accent});final String label,value;final Color accent;@override Widget build(BuildContext context)=>Column(children:[Text(label,style:const TextStyle(fontSize:8,letterSpacing:.8,fontWeight:FontWeight.w900,color:KbColors.textMuted)),const SizedBox(height:5),FittedBox(fit:BoxFit.scaleDown,child:Text(value,style:TextStyle(fontSize:15,fontWeight:FontWeight.w900,color:accent)))]);}
class _CompactState extends StatelessWidget{const _CompactState({required this.icon,required this.label,required this.value,required this.ok});final IconData icon;final String label,value;final bool ok;@override Widget build(BuildContext context)=>Container(height:56,padding:const EdgeInsets.symmetric(horizontal:8),decoration:BoxDecoration(color:KbColors.cardSoft,borderRadius:BorderRadius.circular(12),border:Border.all(color:KbColors.border)),child:Row(children:[Icon(icon,size:17,color:ok?KbColors.cyan:KbColors.textMuted),const SizedBox(width:6),Expanded(child:Column(mainAxisAlignment:MainAxisAlignment.center,crossAxisAlignment:CrossAxisAlignment.start,children:[Text(label,style:const TextStyle(fontSize:7,fontWeight:FontWeight.w900,color:KbColors.textMuted)),const SizedBox(height:2),FittedBox(fit:BoxFit.scaleDown,alignment:Alignment.centerLeft,child:Text(value,style:TextStyle(fontSize:9,fontWeight:FontWeight.w900,color:ok?KbColors.text:KbColors.textMuted)))]))]));}

List<Map<String,dynamic>> _dedupeInstrumentRows(Iterable<Map<String,dynamic>> rows){final seen=<String>{};final out=<Map<String,dynamic>>[];for(final x in rows){final token='${x['instrument_token']??x['instrumentToken']??x['token']??x['pSymbol']??x['p_symbol']??''}';final label=_instrumentLabel(x);final key=token.isNotEmpty?token:'$label|${x['exchange_segment']??x['exchangeSegment']??''}';if(seen.add(key))out.add(x);}return out;}
int _recordCount(dynamic payload){if(payload is List)return payload.length;if(payload is Map){for(final key in ['data','items','rows','result','results','positions','holdings','orders']){final v=payload[key];if(v is List)return v.length;}return payload.isEmpty?0:1;}return 0;}
List<(String,String)> _fundMetrics(dynamic payload){final out=<(String,String)>[];final seen=<String>{};void walk(dynamic v){if(v is Map){for(final e in v.entries){final k='${e.key}';final x=e.value;final lk=k.toLowerCase();if(x is num||double.tryParse('$x')!=null){if(['cash','margin','available','balance','util','used','collateral','limit','fund'].any((needle)=>lk.contains(needle))&&seen.add(lk)){final n=_num(x);out.add((_prettyKey(k),_money(n)));}}else if(x is Map||x is List){walk(x);}}}else if(v is List){for(final x in v)walk(x);}}walk(payload);return out;}
String _prettyKey(String k)=>k.replaceAll(RegExp(r'[_-]+'),' ').split(' ').where((x)=>x.isNotEmpty).map((x)=>x[0].toUpperCase()+x.substring(1)).join(' ');

Iterable<Map<String,dynamic>> _collectInstrumentRows(dynamic payload) sync* {
  if(payload is Map){
    final m=Map<String,dynamic>.from(payload);
    final hasToken=m.keys.any((k)=>['instrument_token','instrumentToken','token','pSymbol','p_symbol'].contains('$k'));
    final hasName=m.keys.any((k)=>['trading_symbol','tradingSymbol','symbol','pTrdSymbol','p_trd_symbol'].contains('$k'));
    if(hasToken&&hasName)yield m;
    for(final v in m.values){yield* _collectInstrumentRows(v);}
  }else if(payload is List){for(final v in payload){yield* _collectInstrumentRows(v);}}
}

Iterable<Map<String,dynamic>> _collectOrderRows(dynamic payload) sync* {
  if(payload is Map){
    final m=Map<String,dynamic>.from(payload);
    if(_orderId(m).isNotEmpty)yield m;
    for(final v in m.values){yield* _collectOrderRows(v);}
  }else if(payload is List){for(final v in payload){yield* _collectOrderRows(v);}}
}

String _orderId(Map<String,dynamic>x)=>'${x['order_id']??x['orderId']??x['nOrdNo']??x['order_number']??x['orderNumber']??''}';
String _instrumentLabel(Map<String,dynamic>x)=>'${x['trading_symbol']??x['tradingSymbol']??x['pTrdSymbol']??x['p_trd_symbol']??x['symbol']??'Instrument'}';

double _extractMarketPrice(dynamic payload){
  final rows=_flattenTickRows(payload);
  for(final r in rows){final p=_num(r['last_traded_price']??r['ltp']??r['lp']??r['price']??r['lastPrice']);if(p>0)return p;}
  return 0;
}

Map<String,dynamic> _map(dynamic v)=>v is Map<String,dynamic>?v:(v is Map?Map<String,dynamic>.from(v):<String,dynamic>{});
double _num(dynamic v){if(v is num)return v.toDouble();return double.tryParse('$v')??0;}
int _int(dynamic v){if(v is int)return v;if(v is num)return v.toInt();return int.tryParse('$v')??0;}
double _double(String s)=>double.tryParse(s.trim())??0;
String _money(double v,{bool sign=false})=>'${sign&&v>=0?'+':''}${NumberFormat.currency(locale:'en_IN',symbol:'\u20B9',decimalDigits:2).format(v)}';
List<Map<String,dynamic>> _flattenTickRows(dynamic payload){final out=<Map<String,dynamic>>[];void walk(dynamic x){if(x is Map){final m=Map<String,dynamic>.from(x);final keys=m.keys.map((e)=>e.toString()).toSet();if(keys.any((k)=>['ltp','last_traded_price','lp','price','instrument_token','token'].contains(k)))out.add(m);for(final v in m.values){if(v is Map||v is List)walk(v);}}else if(x is List){for(final v in x)walk(v);}}walk(payload);return out;}
