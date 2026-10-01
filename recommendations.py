import json, os

def fallback(kind, data):
    budget=float(data['budget']); currency=data.get('currency','INR')
    if kind=='home':
        rooms=data['rooms']; allocations=[round(budget*.4,2),round(budget*.25,2),round(budget*.2,2),round(budget*.15,2)]
        categories=['Furniture','Lighting','Textiles & decor','Reserve']
        items=[{'name':f'{rooms[i%len(rooms)]} essentials shortlist','category':categories[i],'estimated_price':allocations[i],'currency':currency,'platforms':['IKEA','Amazon','Flipkart'],'reason':f'Indicative allocation for {rooms[i%len(rooms)].lower()}; compare dimensions, reviews and delivery costs.'} for i in range(4)]
        title=f'{data.get("style","Modern")} home plan'
    elif kind=='party':
        weights=[.42,.25,.23,.10]; cats=['Food & catering','Venue','Decor','Buffer']; desc=['Compare catering menus on Swiggy/Zomato','Check local venues and OYO for outstation stays','Choose reusable decor within this allowance','Keep this aside for taxes and last-minute needs']
        items=[{'name':f'{cats[i]} budget','category':cats[i],'estimated_price':round(budget*weights[i],2),'currency':currency,'platforms':['Swiggy','Zomato','OYO'] if i<2 else ['Local vendors'],'reason':desc[i]} for i in range(4)]
        title=f'{data.get("event_type","Event")} for {data.get("guests",0)} guests'
    else:
        items=[{'name':n,'category':'Jewelry idea','estimated_price':round(budget*w,2),'currency':currency,'platforms':['Amazon','Flipkart','Local jeweller'],'reason':r} for n,w,r in [('Statement earrings',.32,'A versatile accent suited to the selected occasion and outfit palette.'),('Pendant or necklace',.42,'Keep metal tone and neckline in mind; check material details.'),('Bracelet or ring',.18,'A smaller matching piece can finish the look.'),('Price buffer',.08,'Reserve for delivery, taxes or alterations.')]]
        title=f'{data.get("occasion","Occasion")} jewelry ideas'
    return {'title':title,'summary':'A budget-first starting plan. Adjust the indicative allocations to your local prices and priorities.','items':items,'total_estimate':round(sum(x['estimated_price'] for x in items),2),'currency':currency,'source':'demo','disclaimer':'Illustrative suggestions only. Prices and availability have not been verified against live retailer listings.'}

async def generate_recommendations(kind, data, image_bytes=None, image_type=None):
    key=os.getenv('GEMINI_API_KEY')
    if not key: return fallback(kind,data)
    try:
        from google import genai
        from google.genai import types
        client=genai.Client(api_key=key)
        prompt=f"""You are PocketSmart AI, a practical budget planning assistant. Make a realistic plan for this category: {kind}. User input: {json.dumps(data, ensure_ascii=False)}. Return ONLY valid JSON with keys title, summary, items, total_estimate, currency. items must be an array of 3-6 objects with name, category, estimated_price (number), currency, platforms (array), reason. Respect the given budget and currency; total estimates must not exceed the budget. Suggest retailer/platform names as places to compare, never claim live stock, exact current price, or verified links. Keep advice useful and concise."""
        contents=[prompt]
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes,mime_type=image_type or 'image/jpeg'))
            contents[0]+=' The optional image is outfit inspiration; describe only relevant visible colors/style, and do not infer sensitive traits.'
        response=client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-2.5-flash'),contents=contents,config=types.GenerateContentConfig(response_mime_type='application/json',temperature=.4))
        result=json.loads(response.text)
        result.update({'source':'gemini','disclaimer':'AI-generated suggestions. Retailer availability and prices are not verified.'})
        return result
    except Exception:
        # Keep planner available if the remote AI service is down or returns malformed output.
        result=fallback(kind,data); result['source']='demo-fallback'; result['disclaimer']='Gemini was unavailable, so this illustrative plan was used. Prices and availability are not live.'
        return result
